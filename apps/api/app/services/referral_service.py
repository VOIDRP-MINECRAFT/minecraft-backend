from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.config import get_settings
from apps.api.app.core.security import utc_now
from apps.api.app.models.referral_code import ReferralCode
from apps.api.app.models.referral_link import ReferralLink
from apps.api.app.models.referral_reward_period import ReferralRewardPeriod
from apps.api.app.models.user import User
from apps.api.app.schemas.referral import (
    ReferralCodePreviewResponse,
    ReferralCodeRead,
    ReferralDashboardResponse,
    ReferralLinkItemRead,
    ReferralRewardPeriodRead,
    ReferralTotalsRead,
    RegenerateReferralCodeResponse,
)


class ReferralNotFoundError(Exception):
    pass


class ReferralService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def get_dashboard(self, *, current_user: User) -> ReferralDashboardResponse:
        code = self._get_or_create_code(current_user)
        self._sync_reward_state(current_user)

        recent_links = self.session.execute(
            select(ReferralLink)
            .options(joinedload(ReferralLink.invited).joinedload(User.player_account))
            .where(ReferralLink.inviter_user_id == current_user.id)
            .order_by(ReferralLink.created_at.desc())
            .limit(20)
        ).scalars().all()

        pending = 0
        qualified = 0
        items: list[ReferralLinkItemRead] = []
        for link in recent_links:
            if link.status == "pending":
                pending += 1
            elif link.status == "qualified":
                qualified += 1

            invited = link.invited
            items.append(
                ReferralLinkItemRead(
                    site_login=invited.site_login if invited is not None else "unknown",
                    minecraft_nickname=(
                        invited.player_account.minecraft_nickname
                        if invited is not None and invited.player_account is not None
                        else "unknown"
                    ),
                    status=link.status,
                    created_at=link.created_at,
                    qualified_at=link.qualified_at,
                )
            )

        total_pending = int(
            self.session.scalar(
                select(func.count()).select_from(ReferralLink).where(
                    ReferralLink.inviter_user_id == current_user.id,
                    ReferralLink.status == "pending",
                )
            )
            or 0
        )

        total_qualified = int(
            self.session.scalar(
                select(func.count()).select_from(ReferralLink).where(
                    ReferralLink.inviter_user_id == current_user.id,
                    ReferralLink.status == "qualified",
                )
            )
            or 0
        )

        current_reward = self.session.execute(
            select(ReferralRewardPeriod).where(
                ReferralRewardPeriod.user_id == current_user.id,
                ReferralRewardPeriod.reward_state == "active",
                ReferralRewardPeriod.expires_at > utc_now(),
            )
            .order_by(ReferralRewardPeriod.expires_at.desc())
        ).scalar_one_or_none()

        return ReferralDashboardResponse(
            my_code=ReferralCodeRead(
                code=code.code,
                invite_url=f"{self.settings.website_base_url}/register?ref={code.code}",
            ),
            totals=ReferralTotalsRead(
                pending=total_pending,
                qualified=total_qualified,
                current_rank=current_reward.referral_rank if current_reward else self._rank_for_count(total_qualified),
            ),
            current_reward=(
                ReferralRewardPeriodRead(
                    referral_rank=current_reward.referral_rank,
                    starts_at=current_reward.starts_at,
                    expires_at=current_reward.expires_at,
                    source_qualified_referrals=current_reward.source_qualified_referrals,
                    reward_state=current_reward.reward_state,
                )
                if current_reward is not None
                else None
            ),
            recent_links=items,
        )

    def regenerate_code(self, *, current_user: User) -> RegenerateReferralCodeResponse:
        code = self._get_or_create_code(current_user)
        code.code = self._generate_unique_code(current_user.site_login)
        code.is_active = True
        self.session.commit()
        self.session.refresh(code)

        return RegenerateReferralCodeResponse(
            message="Referral code regenerated successfully.",
            my_code=ReferralCodeRead(
                code=code.code,
                invite_url=f"{self.settings.website_base_url}/register?ref={code.code}",
            ),
        )

    def preview_code(self, code: str) -> ReferralCodePreviewResponse:
        row = self.session.execute(
            select(ReferralCode)
            .options(joinedload(ReferralCode.user).joinedload(User.player_account), joinedload(ReferralCode.user).joinedload(User.public_profile))
            .where(ReferralCode.code == code.upper(), ReferralCode.is_active.is_(True))
        ).unique().scalar_one_or_none()

        if row is None or row.user is None or row.user.player_account is None:
            raise ReferralNotFoundError("referral code was not found")

        return ReferralCodePreviewResponse(
            code=row.code,
            inviter_site_login=row.user.site_login,
            inviter_minecraft_nickname=row.user.player_account.minecraft_nickname,
            inviter_display_name=row.user.public_profile.display_name if row.user.public_profile else None,
        )

    def _get_or_create_code(self, user: User) -> ReferralCode:
        code = self.session.execute(
            select(ReferralCode).where(ReferralCode.user_id == user.id)
        ).scalar_one_or_none()
        if code is not None:
            return code

        code = ReferralCode(
            user_id=user.id,
            code=self._generate_unique_code(user.site_login),
            is_active=True,
        )
        self.session.add(code)
        self.session.commit()
        self.session.refresh(code)
        return code

    def _generate_unique_code(self, seed: str) -> str:
        clean_seed = re.sub(r"[^A-Z0-9]", "", seed.upper())[:8] or "VOIDRP"
        while True:
            candidate = f"{clean_seed}{secrets.token_hex(3).upper()}"[:32]
            exists = self.session.execute(
                select(ReferralCode).where(ReferralCode.code == candidate)
            ).scalar_one_or_none()
            if exists is None:
                return candidate

    def _rank_for_count(self, count: int) -> str | None:
        if count >= 10:
            return "rank_1"
        if count >= 5:
            return "rank_2"
        if count >= 1:
            return "rank_3"
        return None

    def _sync_reward_state(self, user: User) -> None:
        now = utc_now()
        active = self.session.execute(
            select(ReferralRewardPeriod).where(
                ReferralRewardPeriod.user_id == user.id,
                ReferralRewardPeriod.reward_state == "active",
            )
        ).scalars().all()

        changed = False
        for item in active:
            if item.expires_at <= now:
                item.reward_state = "expired"
                changed = True

        qualified_count = int(
            self.session.scalar(
                select(func.count()).select_from(ReferralLink).where(
                    ReferralLink.inviter_user_id == user.id,
                    ReferralLink.status == "qualified",
                )
            )
            or 0
        )
        desired_rank = self._rank_for_count(qualified_count)
        active_current = self.session.execute(
            select(ReferralRewardPeriod).where(
                ReferralRewardPeriod.user_id == user.id,
                ReferralRewardPeriod.reward_state == "active",
                ReferralRewardPeriod.expires_at > now,
            )
        ).scalar_one_or_none()

        should_create = False
        if desired_rank is not None and active_current is None:
            should_create = True
        elif desired_rank is not None and active_current is not None:
            order = {"rank_3": 1, "rank_2": 2, "rank_1": 3}
            if order[desired_rank] > order.get(active_current.referral_rank, 0):
                active_current.reward_state = "expired"
                should_create = True
                changed = True

        if should_create:
            self.session.add(
                ReferralRewardPeriod(
                    user_id=user.id,
                    referral_rank=desired_rank,
                    starts_at=now,
                    expires_at=now + self._thirty_days(),
                    source_qualified_referrals=qualified_count,
                    reward_state="active",
                )
            )
            changed = True

        if changed:
            self.session.commit()

    def _thirty_days(self):
        from datetime import timedelta
        return timedelta(days=30)