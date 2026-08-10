from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)


class TikTokCampaign(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """One published TikTok video announced in-game.

    Created via ``/vrgs tiktok <url>``. Players who open the tracked link earn a
    one-time random reward (see :class:`TikTokClickReward`). Server-scoped.
    """

    __tablename__ = "tiktok_campaigns"

    video_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TikTokClickReward(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A player's click on a campaign link → pending random reward.

    One row per (campaign, player). ``delivered`` flips once the plugin has
    handed out the item in-game. ``created_at`` doubles as the click timestamp.
    """

    __tablename__ = "tiktok_click_rewards"
    __table_args__ = (
        UniqueConstraint("campaign_id", "minecraft_uuid", name="uq_tiktok_reward_campaign_uuid"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("tiktok_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    minecraft_uuid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    minecraft_nickname: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
