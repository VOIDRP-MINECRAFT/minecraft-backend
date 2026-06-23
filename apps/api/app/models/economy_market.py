from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class EconomyMarketItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "economy_market_items"

    material: Mapped[str] = mapped_column(String(192), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    base_buy_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    base_sell_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    current_buy_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    current_sell_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    buy_multiplier: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=1)
    sell_multiplier: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=1)

    demand_score: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    supply_score: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PriceHistorySnapshot(Base):
    __tablename__ = "price_history_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material: Mapped[str] = mapped_column(String(192), nullable=False, index=True)
    buy_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    sell_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    buy_multiplier: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="1")
    sell_multiplier: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="1")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class EconomyShopTransaction(UuidPrimaryKeyMixin, Base):
    __tablename__ = "economy_shop_transactions"

    player_name: Mapped[str] = mapped_column(String(16), nullable=False)
    material: Mapped[str] = mapped_column(String(192), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)

    base_total_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    final_total_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    market_multiplier: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
