"""Admin-editable Battle Pass rewards (per season, per level, per track).

Replaces the plugin's hardcoded rewards.yml as the source of truth: the admin panel edits
these rows, the plugin fetches them (falling back to rewards.yml if the backend is down).
Scoped by season so a new season starts with its own set.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class BattlePassReward(UuidPrimaryKeyMixin, Base):
    __tablename__ = "battlepass_rewards"
    __table_args__ = (
        UniqueConstraint("server_id", "season", "level", "track", name="uq_battlepass_rewards_slot"),
    )

    server_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season: Mapped[str] = mapped_column(String(32), nullable=False, index=True)   # Season.currentKey() (start date)
    level: Mapped[int] = mapped_column(Integer, nullable=False)                    # 1..MAX_LEVEL
    track: Mapped[str] = mapped_column(String(8), nullable=False)                  # "free" | "premium"

    reward_type: Mapped[str] = mapped_column(String(16), nullable=False)           # command|item|money|voidcoin
    command: Mapped[str | None] = mapped_column(String(512), nullable=True)        # for command
    material: Mapped[str | None] = mapped_column(String(64), nullable=True)        # for item (Bukkit Material)
    item_key: Mapped[str | None] = mapped_column(String(128), nullable=True)       # namespaced id (icon/give)
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)              # item count
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)          # money / voidcoin amount
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)           # item id for the WebGUI texture

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
