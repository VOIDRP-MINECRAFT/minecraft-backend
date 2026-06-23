from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BattlePassPremiumGrantRequest(BaseModel):
    minecraft_uuid: str
    minecraft_nickname: str
    days: int = 30
    note: str | None = None


class BattlePassPremiumResponse(BaseModel):
    minecraft_uuid: str
    minecraft_nickname: str
    expires_at: datetime
    granted_by: str | None
    note: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class BattlePassPremiumListResponse(BaseModel):
    items: list[BattlePassPremiumResponse]
    total: int


class BattlePassPremiumStatusResponse(BaseModel):
    minecraft_uuid: str
    has_premium: bool
    expires_at: datetime | None


class BattlePassProgressUpsertRequest(BaseModel):
    minecraft_uuid: str
    minecraft_nickname: str
    season: str
    level: int
    xp: int


class BattlePassPublicProfileResponse(BaseModel):
    minecraft_uuid: str
    season: str | None
    level: int
    xp: int
    has_premium: bool
    premium_expires_at: datetime | None


class AdminBattlePassPlayerInfo(BaseModel):
    minecraft_uuid: str | None
    minecraft_nickname: str
    has_premium: bool
    expires_at: datetime | None
    level: int
    xp: int
    season: str | None


class BattlePassLeaderboardEntry(BaseModel):
    rank: int
    minecraft_nickname: str
    minecraft_uuid: str
    level: int
    xp: int
    has_premium: bool


class BattlePassLeaderboardResponse(BaseModel):
    season: str | None
    entries: list[BattlePassLeaderboardEntry]
    total: int
