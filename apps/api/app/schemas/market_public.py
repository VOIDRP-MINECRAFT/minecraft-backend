from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PublicMarketItemRead(BaseModel):
    material: str
    display_name: str | None = None
    group_key: str = "default"
    base_buy_price: float = 0
    base_sell_price: float = 0
    current_buy_price: float = 0
    current_sell_price: float = 0
    buy_multiplier: float = 1
    sell_multiplier: float = 1
    demand_score: float = 0
    supply_score: float = 0
    trend_percent: float = 0
    spread_percent: float = 0
    demand_state: str = "stable"
    shop_section: str | None = None
    shop_item_index: str | None = None
    enabled: bool = True
    updated_at: datetime | None = None


class PublicMarketItemListResponse(BaseModel):
    total: int
    items: list[PublicMarketItemRead]


class PublicMarketListingRead(BaseModel):
    id: UUID
    nation_slug: str
    nation_title: str
    nation_tag: str
    seller_player_name: str
    seller_role: str
    material: str
    display_name: str | None = None
    total_amount: int
    remaining_amount: int
    sold_amount: int
    current_unit_price: float
    anchor_unit_price: float
    relative_price_multiplier: float
    status: str
    pricing_mode: str
    created_at: datetime
    updated_at: datetime


class PublicMarketListingListResponse(BaseModel):
    total: int
    items: list[PublicMarketListingRead]


class PublicMarketTransactionRead(BaseModel):
    id: UUID
    player_name: str
    material: str
    amount: int
    transaction_type: str
    final_total_price: float
    unit_price: float
    created_at: datetime


class PublicMarketTransactionListResponse(BaseModel):
    total: int
    items: list[PublicMarketTransactionRead]


class PublicMarketSummaryResponse(BaseModel):
    total_items: int
    active_items: int
    active_nation_listings: int
    nation_market_stock_value: float
    shop_transactions_24h: int
    shop_volume_24h: float
    nation_orders_24h: int
    nation_volume_24h: float
    top_demand_items: list[PublicMarketItemRead]
    top_supply_items: list[PublicMarketItemRead]
    updated_at: datetime


class AdminMarketItemPatch(BaseModel):
    enabled: bool | None = None
    display_name: str | None = Field(default=None, max_length=128)
    group_key: str | None = Field(default=None, max_length=64)
    base_buy_price: float | None = Field(default=None, ge=0)
    base_sell_price: float | None = Field(default=None, ge=0)
    current_buy_price: float | None = Field(default=None, ge=0)
    current_sell_price: float | None = Field(default=None, ge=0)
    buy_multiplier: float | None = Field(default=None, ge=0)
    sell_multiplier: float | None = Field(default=None, ge=0)
    reset_scores: bool = False
    reset_to_base: bool = False
    admin_note: str | None = Field(default=None, max_length=500)


class AdminMarketActionResponse(BaseModel):
    ok: bool = True
    message: str
    item: PublicMarketItemRead | None = None


class AdminMarketRecalculateResponse(BaseModel):
    total: int
    changed: int
    message: str = "Market recalculated."


class PriceHistoryPoint(BaseModel):
    recorded_at: datetime
    buy_price: float
    sell_price: float


class PriceHistoryResponse(BaseModel):
    material: str
    total: int
    points: list[PriceHistoryPoint]
