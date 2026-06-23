from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.core.security import utc_now
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.refresh_session import RefreshSession
from apps.api.app.models.user import User
from apps.api.app.schemas.admin import (
    AdminLegacySummaryResponse,
    AdminLegacyUpdateRequest,
    AdminPlayerAccountRead,
    AdminPlayerDiagnostics,
    AdminPlayerRecord,
    AdminPlayersListResponse,
    AdminUserRead,
)
from apps.api.app.utils.normalization import normalize_email, normalize_minecraft_nickname, normalize_site_login


class AdminPlayerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_players(
        self,
        *,
        q: str | None = None,
        legacy_auth_enabled: bool | None = None,
        legacy_hash_present: bool | None = None,
        user_active: bool | None = None,
        limit: int = 50,
    ) -> AdminPlayersListResponse:
        filters = self._build_filters(
            q=q,
            legacy_auth_enabled=legacy_auth_enabled,
            legacy_hash_present=legacy_hash_present,
            user_active=user_active,
        )

        statement = (
            select(PlayerAccount)
            .join(PlayerAccount.user)
            .options(joinedload(PlayerAccount.user))
            .order_by(PlayerAccount.created_at.desc())
            .limit(limit)
        )

        for condition in filters:
            statement = statement.where(condition)

        count_statement = select(func.count()).select_from(PlayerAccount).join(PlayerAccount.user)
        for condition in filters:
            count_statement = count_statement.where(condition)

        total = int(self.session.scalar(count_statement) or 0)
        rows = self.session.execute(statement).unique().scalars().all()

        return AdminPlayersListResponse(
            total=total,
            items=[self._build_record(row) for row in rows],
        )

    def get_player(self, *, player_account_id: UUID) -> AdminPlayerRecord | None:
        player_account = self.session.execute(
            select(PlayerAccount)
            .options(joinedload(PlayerAccount.user))
            .where(PlayerAccount.id == player_account_id)
        ).unique().scalar_one_or_none()

        if player_account is None or player_account.user is None:
            return None

        return self._build_record(player_account)

    def get_summary(self) -> AdminLegacySummaryResponse:
        total_players = int(
            self.session.scalar(select(func.count()).select_from(PlayerAccount)) or 0
        )

        legacy_enabled_players = int(
            self.session.scalar(
                select(func.count())
                .select_from(PlayerAccount)
                .where(PlayerAccount.legacy_auth_enabled.is_(True))
            )
            or 0
        )

        legacy_ready_players = int(
            self.session.scalar(
                select(func.count())
                .select_from(PlayerAccount)
                .where(
                    PlayerAccount.legacy_auth_enabled.is_(True),
                    PlayerAccount.legacy_password_hash.is_not(None),
                    PlayerAccount.legacy_hash_algo.is_not(None),
                )
            )
            or 0
        )

        legacy_missing_hash_players = int(
            self.session.scalar(
                select(func.count())
                .select_from(PlayerAccount)
                .where(
                    PlayerAccount.legacy_auth_enabled.is_(True),
                    or_(
                        PlayerAccount.legacy_password_hash.is_(None),
                        PlayerAccount.legacy_hash_algo.is_(None),
                    ),
                )
            )
            or 0
        )

        launcher_only_players = int(
            self.session.scalar(
                select(func.count())
                .select_from(PlayerAccount)
                .join(PlayerAccount.user)
                .where(
                    User.is_active.is_(True),
                    PlayerAccount.legacy_auth_enabled.is_(False),
                )
            )
            or 0
        )

        return AdminLegacySummaryResponse(
            total_players=total_players,
            legacy_enabled_players=legacy_enabled_players,
            legacy_ready_players=legacy_ready_players,
            legacy_missing_hash_players=legacy_missing_hash_players,
            launcher_only_players=launcher_only_players,
        )

    def update_legacy(
        self,
        *,
        player_account_id: UUID,
        payload: AdminLegacyUpdateRequest,
    ) -> AdminPlayerRecord | None:
        player_account = self.session.execute(
            select(PlayerAccount)
            .options(joinedload(PlayerAccount.user))
            .where(PlayerAccount.id == player_account_id)
        ).unique().scalar_one_or_none()

        if player_account is None or player_account.user is None:
            return None

        if payload.clear_legacy_hash:
            player_account.legacy_password_hash = None
            player_account.legacy_hash_algo = None
        else:
            if payload.legacy_password_hash is not None:
                player_account.legacy_password_hash = payload.legacy_password_hash.strip()

            if payload.legacy_hash_algo is not None:
                player_account.legacy_hash_algo = payload.legacy_hash_algo.strip()

        if payload.legacy_auth_enabled is not None:
            player_account.legacy_auth_enabled = payload.legacy_auth_enabled

        if payload.user_active is not None:
            player_account.user.is_active = payload.user_active

        if payload.revoke_refresh_sessions:
            self._revoke_active_refresh_sessions(player_account.user_id)

        self.session.commit()
        self.session.refresh(player_account)
        self.session.refresh(player_account.user)

        return self._build_record(player_account)

    def _build_filters(
        self,
        *,
        q: str | None,
        legacy_auth_enabled: bool | None,
        legacy_hash_present: bool | None,
        user_active: bool | None,
    ) -> list:
        filters: list = []

        if q:
            raw = q.strip()
            lowered = raw.lower()

            normalized_candidates = {lowered}

            try:
                _, nickname_normalized = normalize_minecraft_nickname(raw)
                normalized_candidates.add(nickname_normalized)
            except ValueError:
                pass

            try:
                _, login_normalized = normalize_site_login(raw)
                normalized_candidates.add(login_normalized)
            except ValueError:
                pass

            normalized_candidates.add(normalize_email(raw))

            exact_conditions = [
                PlayerAccount.minecraft_nickname_normalized.in_(normalized_candidates),
                User.site_login_normalized.in_(normalized_candidates),
                User.email_normalized.in_(normalized_candidates),
            ]

            like_pattern = f"%{raw}%"
            fuzzy_conditions = [
                PlayerAccount.minecraft_nickname.ilike(like_pattern),
                User.site_login.ilike(like_pattern),
                User.email.ilike(like_pattern),
            ]

            filters.append(or_(*exact_conditions, *fuzzy_conditions))

        if legacy_auth_enabled is not None:
            filters.append(PlayerAccount.legacy_auth_enabled.is_(legacy_auth_enabled))

        if legacy_hash_present is True:
            filters.append(PlayerAccount.legacy_password_hash.is_not(None))
        elif legacy_hash_present is False:
            filters.append(PlayerAccount.legacy_password_hash.is_(None))

        if user_active is not None:
            filters.append(User.is_active.is_(user_active))

        return filters

    def _build_record(self, player_account: PlayerAccount) -> AdminPlayerRecord:
        user = player_account.user
        if user is None:
            raise ValueError("player_account.user must be loaded")

        active_refresh_sessions = int(
            self.session.scalar(
                select(func.count())
                .select_from(RefreshSession)
                .where(
                    RefreshSession.user_id == user.id,
                    RefreshSession.revoked_at.is_(None),
                    RefreshSession.expires_at > utc_now(),
                )
            )
            or 0
        )

        legacy_hash_present = bool(player_account.legacy_password_hash)
        legacy_ready = bool(
            player_account.legacy_auth_enabled
            and player_account.legacy_password_hash
            and player_account.legacy_hash_algo
        )

        return AdminPlayerRecord(
            user=AdminUserRead.model_validate(user),
            player_account=AdminPlayerAccountRead.model_validate(player_account),
            diagnostics=AdminPlayerDiagnostics(
                legacy_hash_present=legacy_hash_present,
                legacy_ready=legacy_ready,
                must_use_launcher=bool(user.is_active and not player_account.legacy_auth_enabled),
                refresh_sessions_active=active_refresh_sessions,
            ),
        )

    def _revoke_active_refresh_sessions(self, user_id: UUID) -> None:
        sessions = self.session.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        ).scalars().all()

        now = utc_now()
        for refresh_session in sessions:
            refresh_session.revoked_at = now
            refresh_session.last_used_at = now