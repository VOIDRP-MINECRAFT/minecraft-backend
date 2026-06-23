from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.nation import Nation


class NationMarketListing(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nation_market_listings"

    nation_id: Mapped[UUID] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seller_player_name: Mapped[str] = mapped_column(String(16), nullable=False)
    seller_role: Mapped[str] = mapped_column(String(16), nullable=False)

    material: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_stack_base64: Mapped[str] = mapped_column(Text, nullable=False)

    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    sold_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    anchor_unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    market_price_at_create: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    relative_price_multiplier: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=1)
    current_unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    min_unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    max_unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    pricing_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="relative_to_market")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    nation: Mapped["Nation"] = relationship("Nation")


class NationMarketOrder(UuidPrimaryKeyMixin, Base):
    __tablename__ = "nation_market_orders"

    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("nation_market_listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nation_id: Mapped[UUID] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    buyer_player_name: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    gross_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    fee_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    listing: Mapped[NationMarketListing] = relationship("NationMarketListing")
    nation: Mapped["Nation"] = relationship("Nation")
