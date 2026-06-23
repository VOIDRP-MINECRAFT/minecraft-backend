from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GameNationMembershipSyncRequest(BaseModel):
    leader_minecraft_nickname: str | None = Field(default=None, min_length=3, max_length=16)
    officers: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    replace_missing: bool = True


class GameNationMembershipMemberRead(BaseModel):
    user_id: UUID
    site_login: str
    minecraft_nickname: str
    role: str


class GameNationMembershipSyncResponse(BaseModel):
    message: str
    nation_id: UUID
    nation_slug: str
    leader_user_id: UUID
    matched_members: list[GameNationMembershipMemberRead]
    unresolved_nicknames: list[str]
    removed_user_ids: list[UUID]
    updated_at: datetime


class GameReferralRewardRead(BaseModel):
    referral_rank: str
    starts_at: datetime
    expires_at: datetime
    reward_state: str
    source_qualified_referrals: int
    reward_bundle_key: str
    game_perks: list[str]


class GameReferralRewardResolveResponse(BaseModel):
    minecraft_nickname: str
    player_exists: bool
    has_active_reward: bool
    reward: GameReferralRewardRead | None = None


class GameNationSummaryResponse(BaseModel):
    nation_id: UUID
    nation_slug: str
    title: str
    tag: str
    leader_user_id: UUID
    members_count: int
    officers_count: int
    updated_at: datetime


class GameNationSyncItemRead(BaseModel):
    nation_id: UUID
    nation_slug: str
    title: str
    tag: str
    accent_color: str | None = None
    capital_x: int | None = None
    capital_z: int | None = None
    capital_world: str | None = None
    leader_minecraft_nickname: str | None = None
    officers: list[str]
    members: list[str]
    member_custom_prefixes: dict[str, str] = {}
    updated_at: datetime


class NationCapitalUpdateRequest(BaseModel):
    capital_x: int
    capital_z: int
    capital_world: str = "world"


class GameNationListResponse(BaseModel):
    total: int
    items: list[GameNationSyncItemRead]
