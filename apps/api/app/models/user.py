from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.email_token import EmailToken
    from apps.api.app.models.media_asset import MediaAsset
    from apps.api.app.models.player_account import PlayerAccount
    from apps.api.app.models.player_follow import PlayerFollow
    from apps.api.app.models.player_public_profile import PlayerPublicProfile
    from apps.api.app.models.player_skin import PlayerSkin
    from apps.api.app.models.play_ticket import PlayTicket
    from apps.api.app.models.referral_code import ReferralCode
    from apps.api.app.models.referral_link import ReferralLink
    from apps.api.app.models.referral_reward_period import ReferralRewardPeriod
    from apps.api.app.models.refresh_session import RefreshSession


class User(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    site_login: Mapped[str] = mapped_column(String(32), nullable=False)
    site_login_normalized: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)

    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)

    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    player_account: Mapped["PlayerAccount"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    player_skin: Mapped["PlayerSkin | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    public_profile: Mapped["PlayerPublicProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    email_tokens: Mapped[list["EmailToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    play_tickets: Mapped[list["PlayTicket"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    media_assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    following_links: Mapped[list["PlayerFollow"]] = relationship(
        back_populates="follower",
        cascade="all, delete-orphan",
        foreign_keys="PlayerFollow.follower_user_id",
    )

    follower_links: Mapped[list["PlayerFollow"]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        foreign_keys="PlayerFollow.target_user_id",
    )

    referral_code: Mapped["ReferralCode | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    referrals_sent: Mapped[list["ReferralLink"]] = relationship(
        back_populates="inviter",
        cascade="all, delete-orphan",
        foreign_keys="ReferralLink.inviter_user_id",
    )

    referral_received: Mapped["ReferralLink | None"] = relationship(
        back_populates="invited",
        cascade="all, delete-orphan",
        foreign_keys="ReferralLink.invited_user_id",
        uselist=False,
    )

    referral_reward_periods: Mapped[list["ReferralRewardPeriod"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
