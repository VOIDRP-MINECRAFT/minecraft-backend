from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class PlayerMarketSellOrder(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_market_sell_orders"

    seller_player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(192), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_stack_base64: Mapped[str] = mapped_column(Text, nullable=False)

    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PlayerMarketBuyOrder(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_market_buy_orders"

    buyer_player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(192), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_display_base64: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    reserved_funds: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PlayerMarketTrade(UuidPrimaryKeyMixin, Base):
    __tablename__ = "player_market_trades"

    sell_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("player_market_sell_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    buy_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("player_market_buy_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    seller_player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    buyer_player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(192), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    gross_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    fee_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_seller_proceeds: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)

    item_stack_base64: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    sell_order: Mapped["PlayerMarketSellOrder"] = relationship("PlayerMarketSellOrder")
    buy_order: Mapped["PlayerMarketBuyOrder"] = relationship("PlayerMarketBuyOrder")


class PlayerMarketPendingDelivery(UuidPrimaryKeyMixin, Base):
    __tablename__ = "player_market_pending_deliveries"

    player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    delivery_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # "sell_proceeds" | "item_delivery" | "buy_refund" | "expiry_refund" | "cancel_items"

    trade_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("player_market_trades.id", ondelete="SET NULL"),
        nullable=True,
    )
    sell_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("player_market_sell_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    buy_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("player_market_buy_orders.id", ondelete="SET NULL"),
        nullable=True,
    )

    amount_money: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    amount_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_stack_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_key: Mapped[str | None] = mapped_column(String(192), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class PlayerMarketWebAction(UuidPrimaryKeyMixin, Base):
    """Pending actions created by the browser (WebGUI) that require Vault/inventory processing by the plugin."""
    __tablename__ = "player_market_web_actions"

    player_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # buy | cancel_buy | cancel_sell | pickup
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # pending | processing | done | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
