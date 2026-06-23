from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field

MoneyAmount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
MoneyBalance = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]


class NationStatsRead(BaseModel):
    nation_id: UUID
    treasury_balance: float
    territory_points: int
    total_playtime_minutes: int
    pvp_kills: int
    mob_kills: int
    boss_kills: int
    deaths: int
    blocks_placed: int
    blocks_broken: int
    events_completed: int
    prestige_score: int
    updated_at: datetime


class NationStatsUpsertRequest(BaseModel):
    nation_slug: str
    treasury_balance: float = 0
    territory_points: int = 0
    total_playtime_minutes: int = 0
    pvp_kills: int = 0
    mob_kills: int = 0
    boss_kills: int = 0
    deaths: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0
    events_completed: int = 0
    prestige_score: int = 0


class NationStatsUpsertResponse(BaseModel):
    message: str
    nation_id: UUID
    nation_slug: str
    updated_at: datetime


class NationRankingItemRead(BaseModel):
    nation_id: UUID
    slug: str
    title: str
    tag: str
    accent_color: str | None = None
    banner_url: str | None = None
    icon_url: str | None = None
    members_count: int
    treasury_balance: float
    territory_points: int
    total_playtime_minutes: int
    pvp_kills: int
    mob_kills: int
    prestige_score: int
    score: float


class NationRankingResponse(BaseModel):
    items: list[NationRankingItemRead]


class NationTreasuryTransactionRead(BaseModel):
    id: UUID
    transaction_type: str
    nation_id: UUID | None = None
    counterparty_nation_id: UUID | None = None
    alliance_id: UUID | None = None
    created_by_user_id: UUID | None = None
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    comment: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NationTreasuryTransactionListResponse(BaseModel):
    total: int
    items: list[NationTreasuryTransactionRead]


class NationTreasuryDepositRequest(BaseModel):
    amount: MoneyAmount
    comment: str | None = Field(default=None, max_length=500)


class NationTreasuryWithdrawRequest(BaseModel):
    amount: MoneyAmount
    comment: str | None = Field(default=None, max_length=500)


class NationTreasuryPlayerDonateInternalRequest(BaseModel):
    nation_slug: str = Field(min_length=3, max_length=64)
    amount: MoneyAmount
    minecraft_nickname: str = Field(min_length=1, max_length=16)
    comment: str | None = Field(default=None, max_length=500)


class NationTreasuryPlayerWithdrawInternalRequest(BaseModel):
    nation_slug: str = Field(min_length=3, max_length=64)
    amount: MoneyAmount
    minecraft_nickname: str = Field(min_length=1, max_length=16)
    comment: str | None = Field(default=None, max_length=500)


class NationTreasuryActionResponse(BaseModel):
    message: str
    nation_slug: str
    new_treasury_balance: Decimal


class NationDonorItemRead(BaseModel):
    minecraft_nickname: str
    total_amount: Decimal
    donations_count: int
    last_donated_at: datetime | None = None


class NationDonorListResponse(BaseModel):
    total: int
    items: list[NationDonorItemRead]


class NationMemberStatSnapshotItemRequest(BaseModel):
    minecraft_nickname: str = Field(min_length=1, max_length=16)
    total_playtime_minutes: int = 0
    pvp_kills: int = 0
    mob_kills: int = 0
    deaths: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0
    current_balance: MoneyBalance = Decimal("0.00")
    completed_quests: int = 0
    source: str = Field(default="cached", max_length=32)
    last_seen_at: datetime | None = None


class NationMemberStatsSyncRequest(BaseModel):
    nation_slug: str = Field(min_length=3, max_length=64)
    territory_points: int = 0
    boss_kills: int = 0
    events_completed: int = 0
    prestige_bonus: int = 0
    members: list[NationMemberStatSnapshotItemRequest] = Field(default_factory=list)


class NationMemberStatsSyncResponse(BaseModel):
    message: str
    nation_id: UUID
    nation_slug: str
    member_snapshots_synced: int
    updated_at: datetime


class PlayerStatCacheItemRequest(BaseModel):
    minecraft_nickname: str = Field(min_length=1, max_length=16)
    total_playtime_minutes: int = 0
    pvp_kills: int = 0
    mob_kills: int = 0
    deaths: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0
    current_balance: MoneyBalance = Decimal("0.00")
    completed_quests: int = 0
    source: str = Field(default="live", max_length=32)
    last_seen_at: datetime | None = None


class PlayerStatCacheSyncRequest(BaseModel):
    players: list[PlayerStatCacheItemRequest] = Field(default_factory=list)


class PlayerStatCacheSyncResponse(BaseModel):
    synced: int