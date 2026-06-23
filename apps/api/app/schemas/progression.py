from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from apps.api.app.schemas.common import ORMModel


class TierUnlockRequest(BaseModel):
    minecraft_uuid: str
    minecraft_nickname: str
    tier_name: str


class TierUnlockResponse(BaseModel):
    accepted: bool
    already_had: bool


class ProgressionTierRead(ORMModel):
    tier_name: str
    tier_label: str
    unlocked_at: datetime


class PlayerProgressionRead(BaseModel):
    minecraft_nickname: str
    minecraft_uuid: str
    tiers: list[ProgressionTierRead]
    current_tier: str | None
    current_tier_label: str | None


class LeaderboardEntryRead(BaseModel):
    rank: int
    minecraft_nickname: str
    minecraft_uuid: str
    unlocked_at: datetime


class TierLeaderboardRead(BaseModel):
    tier_name: str
    tier_label: str
    entries: list[LeaderboardEntryRead]


class FullLeaderboardRead(BaseModel):
    tiers: list[TierLeaderboardRead]
