from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EconomyMarketPriceRead(BaseModel):
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
    enabled: bool = True
    updated_at: datetime | None = None
    shop_section: str | None = None
    shop_item_index: str | None = None
    source: str | None = None


class EconomyMarketPriceListResponse(BaseModel):
    total: int
    items: list[EconomyMarketPriceRead]


class EconomyMarketRecalculateResponse(BaseModel):
    total: int
    changed: int


class EconomyShopTransactionCreate(BaseModel):
    player_name: str = Field(min_length=3, max_length=16)
    material: str = Field(min_length=1, max_length=192)
    amount: int = Field(gt=0, le=1_000_000)
    transaction_type: str = Field(min_length=2, max_length=32)
    base_total_price: float = Field(default=0, ge=0)
    final_total_price: float = Field(default=0, ge=0)
    market_multiplier: float = Field(default=1, ge=0)
    display_name: str | None = Field(default=None, max_length=128)
    shop_section: str | None = Field(default=None, max_length=192)
    shop_item_index: str | None = Field(default=None, max_length=192)
    source: str | None = Field(default="economyshopgui", max_length=64)
    metadata_json: dict = Field(default_factory=dict)


class EconomyShopTransactionRead(BaseModel):
    id: UUID
    material: str
    amount: int
    transaction_type: str
    final_total_price: float
    created_at: datetime


class NationMarketListingCreate(BaseModel):
    nation_slug: str = Field(min_length=2, max_length=64)
    seller_player_name: str = Field(min_length=3, max_length=16)
    seller_role: str = Field(min_length=3, max_length=16)
    material: str = Field(min_length=1, max_length=192)
    display_name: str | None = Field(default=None, max_length=128)
    item_stack_base64: str = Field(min_length=10)
    total_amount: int = Field(gt=0, le=1_000_000)
    anchor_unit_price: float = Field(gt=0)
    market_price_at_create: float = Field(default=0, ge=0)
    metadata_json: dict = Field(default_factory=dict)


class NationMarketListingRead(BaseModel):
    id: UUID
    nation_slug: str
    nation_title: str
    nation_tag: str
    seller_player_name: str
    seller_role: str
    material: str
    display_name: str | None = None
    item_stack_base64: str
    total_amount: int
    remaining_amount: int
    sold_amount: int
    anchor_unit_price: float
    market_price_at_create: float
    relative_price_multiplier: float
    current_unit_price: float
    min_unit_price: float
    max_unit_price: float
    status: str
    pricing_mode: str
    created_at: datetime
    updated_at: datetime


class NationMarketListingListResponse(BaseModel):
    total: int
    items: list[NationMarketListingRead]


class NationMarketPurchaseRequest(BaseModel):
    buyer_player_name: str = Field(min_length=3, max_length=16)
    amount: int = Field(gt=0, le=100_000)
    expected_unit_price: float = Field(gt=0)


class NationMarketPurchaseResponse(BaseModel):
    message: str
    listing: NationMarketListingRead
    purchased_amount: int
    unit_price: float
    gross_total: float
    fee_amount: float
    net_total: float
    item_stack_base64: str


class NationMarketCancelRequest(BaseModel):
    requester_player_name: str = Field(min_length=3, max_length=16)


class NationMarketCancelResponse(BaseModel):
    message: str
    listing: NationMarketListingRead
    returned_amount: int
    item_stack_base64: str
