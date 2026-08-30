"""Void Upgrader — spend Void Coins to gamble toward an item reward.

Two tables:
- ``void_upgrader_rewards`` — the curated reward pool (per server). Each row is an item
  with a Void-Coin value; the pool is seeded from market prices and tuned by admins.
- ``void_upgrader_spins`` — a log of every spin (stake, odds, roll, outcome) for history
  and provable fairness.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


class VoidUpgraderReward(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "void_upgrader_rewards"
    __table_args__ = (
        UniqueConstraint("server_id", "item_key", name="uq_void_upgrader_rewards_server_item"),
    )

    item_key: Mapped[str] = mapped_column(String(128), nullable=False)          # namespace:id
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    vc_value: Mapped[int] = mapped_column(BigInteger, nullable=False)           # value in Void Coins
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)     # how many to give
    tier: Mapped[str] = mapped_column(String(24), nullable=False, default="common")
    give_command: Mapped[str | None] = mapped_column(String(256), nullable=True)  # optional override
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class VoidUpgraderSpin(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "void_upgrader_spins"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    minecraft_nickname: Mapped[str] = mapped_column(String(48), nullable=False)

    stake: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reward_item_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reward_display: Mapped[str] = mapped_column(String(128), nullable=False)
    reward_vc_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    win_chance: Mapped[float] = mapped_column(Float, nullable=False)
    roll: Mapped[float] = mapped_column(Float, nullable=False)
    won: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # provable fairness
    server_seed: Mapped[str] = mapped_column(String(64), nullable=False)
    client_seed: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
