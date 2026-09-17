"""Travelling trader (скупщик): a limited, shared stock that visits spawn on a schedule.

The stock is the point: whatever players automate, the trader only buys what he arrived with,
so the money a visit can put into the economy is capped (plus an explicit payout budget).

* ``TraderSettings``     — one row per server; tunables live in ``config`` (see TraderConfig).
* ``TraderCatalogItem``  — what may appear: item, rarity (1..3), phase, base value per unit.
* ``TraderVisit``        — one arrival (scheduled slot or forced by an admin), rolled once.
* ``TraderStock``        — the rolled slots of a visit with a shared remaining quantity.
* ``TraderSession``      — issued when a player right-clicks the NPC; the page works only with it.
* ``TraderTransaction``  — one trade: stock reserved on request, settled by the plugin.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class TraderSettings(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "trader_settings"
    __table_args__ = (UniqueConstraint("server_id", name="uq_trader_settings_server"),)

    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Phases open once the average battle pass level of active players reaches the configured
    # threshold, and stay open (players joining later don't close them again).
    mid_unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TraderCatalogItem(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "trader_catalog_items"
    __table_args__ = (UniqueConstraint("server_id", "item_key", name="uq_trader_catalog_server_item"),)

    item_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rarity: Mapped[int] = mapped_column(SmallInteger, nullable=False)          # 1 | 2 | 3
    phase: Mapped[str] = mapped_column(String(8), nullable=False)              # early | mid | end
    unit_value: Mapped[float] = mapped_column(Float, nullable=False)           # base coins per item
    can_buy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)    # trader buys from players
    can_sell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)   # trader sells to players
    # Optional per-item quantity range; empty = the rarity range from the config.
    qty_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qty_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TraderVisit(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "trader_visits"
    __table_args__ = (UniqueConstraint("server_id", "starts_at", name="uq_trader_visits_server_start"),)

    kind: Mapped[str] = mapped_column(String(16), nullable=False)              # normal | weekend | elite
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phases: Mapped[str] = mapped_column(String(32), nullable=False)            # e.g. "early,mid"
    payout_budget: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")  # schedule | admin
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    announced_soon_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announced_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TraderStock(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "trader_stock"
    __table_args__ = (UniqueConstraint("visit_id", "side", "slot", name="uq_trader_stock_visit_side_slot"),)

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("trader_visits.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)               # buy (from players) | sell (to players)
    slot: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    catalog_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trader_catalog_items.id", ondelete="SET NULL"), nullable=True
    )
    item_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rarity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    qty_total: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_left: Mapped[int] = mapped_column(Integer, nullable=False)


class TraderSession(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "trader_sessions"

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("trader_visits.id", ondelete="CASCADE"), nullable=False)
    player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TraderTransaction(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "trader_transactions"

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("trader_visits.id", ondelete="CASCADE"), nullable=False, index=True)
    stock_id: Mapped[UUID] = mapped_column(ForeignKey("trader_stock.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    item_key: Mapped[str] = mapped_column(String(128), nullable=False)
    qty_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)  # pending|done|failed|expired
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    web_action_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
