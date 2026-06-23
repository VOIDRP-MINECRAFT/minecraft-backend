from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core.security import (
    build_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    utc_now,
    verify_password,
)
from apps.api.app.models.email_token import EmailToken, EmailTokenPurpose
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_public_profile import PlayerPublicProfile
from apps.api.app.models.referral_code import ReferralCode
from apps.api.app.models.referral_link import ReferralLink
from apps.api.app.models.referral_reward_period import ReferralRewardPeriod
from apps.api.app.models.refresh_session import RefreshSession
from apps.api.app.models.user import User
from apps.api.app.repositories.user_repository import UserRepository
from apps.api.app.services.email_service import EmailMessage, EmailService, build_email_layout
from apps.api.app.utils.normalization import (
    normalize_email,
    normalize_minecraft_nickname,
    normalize_site_login,
)

SLUG_CLEANUP_PATTERN = re.compile(r"[^a-z0-9._-]+")


class AuthError(Exception):
    pass


class ConflictError(AuthError):
    pass


class AuthenticationError(AuthError):
    pass


class TokenValidationError(AuthError):
    pass


@dataclass(slots=True)
class LoginResult:
    access_token: str
    access_expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: User
    player_account: PlayerAccount


class AuthService:
    def __init__(self, session: Session, email_service: EmailService) -> None:
        self.session = session
        self.email_service = email_service
        self.user_repository = UserRepository(session)
        self.settings = get_settings()

    def register_user(
        self,
        *,
        site_login: str,
        minecraft_nickname: str,
        email: str,
        password: str,
        referral_code: str | None = None,
    ) -> tuple[User, PlayerAccount]:
        login_raw, login_normalized = normalize_site_login(site_login)
        nickname_raw, nickname_normalized = normalize_minecraft_nickname(minecraft_nickname)
        email_normalized = normalize_email(email)

        if self.user_repository.get_by_site_login_normalized(login_normalized):
            raise ConflictError("site_login is already taken")

        if self.user_repository.get_by_email_normalized(email_normalized):
            raise ConflictError("email is already registered")

        existing_player = self.session.execute(
            select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == nickname_normalized)
        ).scalar_one_or_none()
        if existing_player:
            raise ConflictError("minecraft_nickname is already linked to another account")

        inviter_user: User | None = None
        referral_code_value: str | None = None
        if referral_code:
            referral_code_value = referral_code.strip().upper()
            inviter_user = self._get_inviter_by_referral_code(referral_code_value)
            if inviter_user is None:
                raise ValueError("referral_code is invalid")

        user = User(
            site_login=login_raw,
            site_login_normalized=login_normalized,
            email=email.strip(),
            email_normalized=email_normalized,
            password_hash=hash_password(password),
            email_verified=False,
            is_active=True,
        )
        player_account = PlayerAccount(
            minecraft_nickname=nickname_raw,
            minecraft_nickname_normalized=nickname_normalized,
            nickname_locked=True,
            legacy_auth_enabled=False,
        )
        user.player_account = player_account

        public_profile = PlayerPublicProfile(
            slug=self._generate_unique_profile_slug(login_raw),
            display_name=nickname_raw,
            bio=None,
            status_text=None,
            theme_mode="default",
            accent_color=None,
            is_public=True,
            allow_followers_list_public=True,
            allow_friends_list_public=True,
            allow_profile_comments=False,
        )
        user.public_profile = public_profile

        own_referral_code = ReferralCode(
            code=self._generate_unique_referral_code(login_raw),
            is_active=True,
        )
        user.referral_code = own_referral_code

        self.user_repository.add(user)
        self.session.flush()

        if inviter_user is not None and referral_code_value is not None:
            referral_link = ReferralLink(
                inviter_user_id=inviter_user.id,
                invited_user_id=user.id,
                referral_code=referral_code_value,
                status="pending",
                qualified_at=None,
            )
            self.session.add(referral_link)

        self._issue_email_token(user=user, purpose=EmailTokenPurpose.VERIFY_EMAIL)
        self.session.commit()
        self.session.refresh(user)
        self.session.refresh(player_account)

        return user, player_account

    def login(self, *, login: str, password: str, device_name: str) -> LoginResult:
        normalized_login = normalize_email(login)
        user = self.user_repository.get_by_login_or_email_normalized_with_player_account(normalized_login)

        if user is None or not verify_password(password, user.password_hash):
            raise AuthenticationError("invalid credentials")

        if not user.is_active:
            raise AuthenticationError("account is disabled")

        return self._issue_session(user=user, device_name=device_name)

    def refresh(self, *, raw_refresh_token: str, device_name: str) -> LoginResult:
        refresh_session = self.session.execute(
            select(RefreshSession).where(RefreshSession.token_hash == hash_opaque_token(raw_refresh_token))
        ).scalar_one_or_none()

        if refresh_session is None:
            raise AuthenticationError("refresh token is invalid")
        if refresh_session.revoked_at is not None:
            raise AuthenticationError("refresh token is revoked")
        if refresh_session.expires_at <= utc_now():
            raise AuthenticationError("refresh token is expired")

        user = self.user_repository.get_by_id_with_player_account(refresh_session.user_id)
        if user is None:
            raise AuthenticationError("user is not available")

        refresh_session.revoked_at = utc_now()
        refresh_session.last_used_at = utc_now()
        self.session.flush()

        return self._issue_session(user=user, device_name=device_name)

    def logout(self, *, raw_refresh_token: str) -> None:
        refresh_session = self.session.execute(
            select(RefreshSession).where(RefreshSession.token_hash == hash_opaque_token(raw_refresh_token))
        ).scalar_one_or_none()

        if refresh_session is None:
            return

        refresh_session.revoked_at = utc_now()
        refresh_session.last_used_at = utc_now()
        self.session.commit()

    def verify_email(self, *, raw_token: str) -> User:
        email_token = self._get_valid_email_token(raw_token=raw_token, purpose=EmailTokenPurpose.VERIFY_EMAIL)
        user = self.session.execute(select(User).where(User.id == email_token.user_id)).scalar_one()
        user.email_verified = True
        email_token.consumed_at = utc_now()
        self.session.commit()
        self.session.refresh(user)
        return user

    def resend_verification_email(self, *, email: str) -> None:
        email_normalized = normalize_email(email)
        user = self.user_repository.get_by_email_normalized(email_normalized)
        if user is None or user.email_verified is True:
            return

        self._consume_outstanding_email_tokens(user.id, EmailTokenPurpose.VERIFY_EMAIL)
        self._issue_email_token(user=user, purpose=EmailTokenPurpose.VERIFY_EMAIL)
        self.session.commit()

    def request_password_reset(self, *, email: str) -> None:
        email_normalized = normalize_email(email)
        user = self.user_repository.get_by_email_normalized(email_normalized)
        if user is None or not user.is_active:
            return

        self._consume_outstanding_email_tokens(user.id, EmailTokenPurpose.RESET_PASSWORD)
        self._issue_email_token(user=user, purpose=EmailTokenPurpose.RESET_PASSWORD)
        self.session.commit()

    def reset_password(self, *, raw_token: str, new_password: str) -> User:
        email_token = self._get_valid_email_token(raw_token=raw_token, purpose=EmailTokenPurpose.RESET_PASSWORD)
        user = self.session.execute(select(User).where(User.id == email_token.user_id)).scalar_one()
        user.password_hash = hash_password(new_password)
        email_token.consumed_at = utc_now()

        refresh_sessions = self.session.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
        ).scalars().all()
        now = utc_now()
        for refresh_session in refresh_sessions:
            refresh_session.revoked_at = now
            refresh_session.last_used_at = now

        self.session.commit()
        self.session.refresh(user)
        return user

    def _issue_session(self, *, user: User, device_name: str) -> LoginResult:
        player_account = user.player_account
        access_token, access_expires_at = build_access_token(user.id)
        raw_refresh_token = generate_opaque_token()
        refresh_expires_at = utc_now() + timedelta(days=self.settings.refresh_token_expire_days)

        refresh_session = RefreshSession(
            user_id=user.id,
            token_hash=hash_opaque_token(raw_refresh_token),
            device_name=device_name,
            issued_at=utc_now(),
            expires_at=refresh_expires_at,
            last_used_at=utc_now(),
        )
        self.session.add(refresh_session)
        self.session.commit()

        access_expires_in = int((access_expires_at - utc_now()).total_seconds())
        refresh_expires_in = int((refresh_expires_at - utc_now()).total_seconds())

        return LoginResult(
            access_token=access_token,
            access_expires_in=max(access_expires_in, 0),
            refresh_token=raw_refresh_token,
            refresh_expires_in=max(refresh_expires_in, 0),
            user=user,
            player_account=player_account,
        )

    def _issue_email_token(self, *, user: User, purpose: EmailTokenPurpose) -> EmailToken:
        raw_token = generate_opaque_token()
        email_token = EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_opaque_token(raw_token),
            expires_at=utc_now() + timedelta(hours=self.settings.email_token_expire_hours),
        )
        self.session.add(email_token)
        self.session.flush()

        if purpose == EmailTokenPurpose.VERIFY_EMAIL:
            confirm_url = (
                f"{self.settings.public_api_base_url}{self.settings.api_v1_prefix}"
                f"/auth/verify-email/confirm?token={raw_token}"
            )
            subject = "VoidRP: подтверждение почты"
            body = (
                "Добро пожаловать в VoidRP.\n\n"
                "Для завершения регистрации подтвердите адрес электронной почты:\n"
                f"{confirm_url}\n\n"
                f"Ссылка действует {self.settings.email_token_expire_hours} ч.\n"
                "Если это были не вы, просто проигнорируйте письмо.\n"
            )
            html = build_email_layout(
                title="Подтвердите почту",
                intro="Нажмите на кнопку ниже, чтобы подтвердить адрес электронной почты для аккаунта VoidRP.",
                action_url=confirm_url,
                action_text="Подтвердить почту",
                footer="Если вы не регистрировались в VoidRP, просто проигнорируйте это письмо.",
            )
        else:
            reset_url = f"{self.settings.website_base_url}/reset-password?token={raw_token}"
            subject = "VoidRP: сброс пароля"
            body = (
                "Вы запросили сброс пароля аккаунта VoidRP.\n\n"
                "Откройте страницу сброса пароля:\n"
                f"{reset_url}\n\n"
                f"Ссылка действует {self.settings.email_token_expire_hours} ч.\n"
                "Если это были не вы, просто проигнорируйте письмо.\n"
            )
            html = build_email_layout(
                title="Сброс пароля",
                intro="Нажмите на кнопку ниже, чтобы перейти к установке нового пароля для аккаунта VoidRP.",
                action_url=reset_url,
                action_text="Сбросить пароль",
                footer="Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо.",
            )

        self.email_service.send(
            EmailMessage(
                to_email=user.email,
                subject=subject,
                body=body,
                html=html,
            )
        )
        return email_token

    def _consume_outstanding_email_tokens(self, user_id: UUID, purpose: EmailTokenPurpose) -> None:
        outstanding_tokens = self.session.execute(
            select(EmailToken).where(
                EmailToken.user_id == user_id,
                EmailToken.purpose == purpose,
                EmailToken.consumed_at.is_(None),
            )
        ).scalars().all()

        now = utc_now()
        for token in outstanding_tokens:
            token.consumed_at = now

    def _get_valid_email_token(self, *, raw_token: str, purpose: EmailTokenPurpose) -> EmailToken:
        token_hash = hash_opaque_token(raw_token)
        email_token = self.session.execute(
            select(EmailToken).where(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == purpose,
            )
        ).scalar_one_or_none()

        if email_token is None:
            raise TokenValidationError("token is invalid")
        if email_token.consumed_at is not None:
            raise TokenValidationError("token is already used")
        if email_token.expires_at <= utc_now():
            raise TokenValidationError("token is expired")

        return email_token

    def _get_inviter_by_referral_code(self, code: str) -> User | None:
        row = self.session.execute(
            select(ReferralCode).where(
                ReferralCode.code == code,
                ReferralCode.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self.session.get(User, row.user_id)

    def _generate_unique_profile_slug(self, seed: str) -> str:
        base = SLUG_CLEANUP_PATTERN.sub("-", seed.strip().lower()).strip("-._")
        if not base:
            base = "player"
        base = base[:48]

        candidate = base
        suffix = 1
        while self.session.execute(
            select(PlayerPublicProfile).where(PlayerPublicProfile.slug == candidate)
        ).scalar_one_or_none() is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"[:64]
        return candidate

    def _generate_unique_referral_code(self, seed: str) -> str:
        clean_seed = re.sub(r"[^A-Z0-9]", "", seed.upper())[:8] or "VOIDRP"
        while True:
            random_tail = secrets.token_hex(3).upper()
            candidate = f"{clean_seed}{random_tail}"[:32]
            exists = self.session.execute(
                select(ReferralCode).where(ReferralCode.code == candidate)
            ).scalar_one_or_none()
            if exists is None:
                return candidate