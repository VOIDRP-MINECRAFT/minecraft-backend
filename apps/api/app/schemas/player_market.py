from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_MAX_UNIT_PRICE = 1_000_000_000.0  # 1 billion — prevents overflow in price*amount products


def _finite_positive(v: float, field_name: str) -> float:
    if not math.isfinite(v):
        raise ValueError(f"{field_name} must be a finite number")
    return v


# ── Request schemas (plugin → backend via X-Game-Auth-Secret) ─────────────────

class PlayerMarketSellOrderCreate(BaseModel):
    seller_player_name: str = Field(min_length=1, max_length=16)
    item_key: str = Field(min_length=3, max_length=192)
    display_name: str | None = Field(default=None, max_length=128)
    item_stack_base64: str = Field(min_length=10)
    total_amount: int = Field(gt=0, le=100_000)
    unit_price: float = Field(gt=0, le=_MAX_UNIT_PRICE)
    metadata_json: dict = Field(default_factory=dict)
    is_premium: bool = False

    @field_validator("unit_price", mode="before")
    @classmethod
    def unit_price_finite(cls, v: float) -> float:
        return _finite_positive(v, "unit_price")


class PlayerMarketBuyOrderCreate(BaseModel):
    buyer_player_name: str = Field(min_length=1, max_length=16)
    item_key: str = Field(min_length=3, max_length=192)
    display_name: str | None = Field(default=None, max_length=128)
    item_display_base64: str | None = Field(default=None)
    total_amount: int = Field(gt=0, le=100_000)
    unit_price: float = Field(gt=0, le=_MAX_UNIT_PRICE)
    reserved_funds: float = Field(gt=0)
    metadata_json: dict = Field(default_factory=dict)
    is_premium: bool = False

    @field_validator("unit_price", "reserved_funds", mode="before")
    @classmethod
    def prices_finite(cls, v: float) -> float:
        return _finite_positive(v, "price")


class PlayerMarketCancelOrderRequest(BaseModel):
    requester_player_name: str = Field(min_length=1, max_length=16)


class PlayerMarketDeliveryAckRequest(BaseModel):
    delivery_ids: list[str] = Field(default_factory=list)


# ── Read schemas ───────────────────────────────────────────────────────────────

class PlayerMarketSellOrderRead(BaseModel):
    id: UUID
    seller_player_name: str
    item_key: str
    display_name: str | None
    item_stack_base64: str
    total_amount: int
    remaining_amount: int
    filled_amount: int
    unit_price: float
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlayerMarketSellOrderPublicRead(BaseModel):
    """Like SellOrderRead but without item_stack_base64 for public endpoints."""
    id: UUID
    seller_player_name: str
    item_key: str
    display_name: str | None
    total_amount: int
    remaining_amount: int
    filled_amount: int
    unit_price: float
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class PlayerMarketBuyOrderRead(BaseModel):
    id: UUID
    buyer_player_name: str
    item_key: str
    display_name: str | None
    item_display_base64: str | None = None
    total_amount: int
    remaining_amount: int
    filled_amount: int
    unit_price: float
    reserved_funds: float
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlayerMarketTradeRead(BaseModel):
    id: UUID
    sell_order_id: UUID | None
    buy_order_id: UUID | None
    seller_player_name: str
    buyer_player_name: str
    item_key: str
    display_name: str | None
    amount: int
    unit_price: float
    gross_total: float
    fee_amount: float
    net_seller_proceeds: float
    created_at: datetime

    model_config = {"from_attributes": True}


class PlayerMarketPendingDeliveryRead(BaseModel):
    id: UUID
    player_name: str
    delivery_type: str
    amount_money: float
    amount_items: int
    item_stack_base64: str | None
    item_key: str | None
    display_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Composite response schemas ─────────────────────────────────────────────────

class PlayerMarketImmediateFill(BaseModel):
    trade_id: UUID
    matched_order_id: UUID
    amount_filled: int
    unit_price: float
    gross_total: float
    fee_amount: float
    net_seller_proceeds: float
    item_stack_base64: str
    funds_released_to_seller: float
    funds_returned_to_buyer: float
    seller_player_name: str = ""
    buyer_player_name: str = ""


class PlayerMarketCreateSellOrderResponse(BaseModel):
    message: str
    order: PlayerMarketSellOrderRead
    immediate_fills: list[PlayerMarketImmediateFill] = Field(default_factory=list)


class PlayerMarketCreateBuyOrderResponse(BaseModel):
    message: str
    order: PlayerMarketBuyOrderRead
    immediate_fills: list[PlayerMarketImmediateFill] = Field(default_factory=list)


class PlayerMarketCancelSellOrderResponse(BaseModel):
    message: str
    order: PlayerMarketSellOrderRead
    returned_amount: int
    cancel_fee_coins: float
    item_stack_base64: str


class PlayerMarketCancelBuyOrderResponse(BaseModel):
    message: str
    order: PlayerMarketBuyOrderRead
    returned_funds: float


class PlayerMarketOrderBookEntry(BaseModel):
    unit_price: float
    total_amount: int
    order_count: int


class PlayerMarketOrderBookResponse(BaseModel):
    item_key: str
    sell_side: list[PlayerMarketOrderBookEntry]
    buy_side: list[PlayerMarketOrderBookEntry]
    last_trade_price: float | None
    last_trade_at: datetime | None
    spread: float | None


class PlayerMarketSellOrderListResponse(BaseModel):
    total: int
    items: list[PlayerMarketSellOrderPublicRead]


class PlayerMarketBuyOrderListResponse(BaseModel):
    total: int
    items: list[PlayerMarketBuyOrderRead]


class PlayerMarketTradeListResponse(BaseModel):
    total: int
    items: list[PlayerMarketTradeRead]


class PlayerMarketPendingDeliveriesResponse(BaseModel):
    total: int
    deliveries: list[PlayerMarketPendingDeliveryRead]


class PlayerMarketExpireResponse(BaseModel):
    expired_sell_orders: int
    expired_buy_orders: int


class PlayerMarketItemSummary(BaseModel):
    """Aggregated per-item view for the market hub page."""
    item_key: str
    display_name: str | None
    best_sell_price: float | None
    best_buy_price: float | None
    active_sell_orders: int
    active_buy_orders: int
    volume_24h: int
    last_trade_price: float | None
    last_trade_at: datetime | None


class PlayerMarketItemSummaryListResponse(BaseModel):
    total: int
    items: list[PlayerMarketItemSummary]
