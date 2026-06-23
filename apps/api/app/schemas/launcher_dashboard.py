from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from apps.api.app.schemas.nation_stats import NationStatsRead


class LauncherDashboardNationRead(BaseModel):
    id: UUID
    slug: str
    title: str
    tag: str
    accent_color: str | None = None
    role: str | None = None
    icon_url: str | None = None
    icon_preview_url: str | None = None
    banner_url: str | None = None
    banner_preview_url: str | None = None
    background_url: str | None = None
    background_preview_url: str | None = None
    alliance_title: str | None = None
    alliance_tag: str | None = None


class LauncherDashboardPlayerStatsRead(BaseModel):
    user_id: UUID | None = None
    minecraft_nickname: str = ""
    total_playtime_minutes: int = 0
    pvp_kills: int = 0
    mob_kills: int = 0
    deaths: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0
    current_balance: float = 0
    completed_quests: int = 0
    source: str = "missing"
    last_seen_at: datetime | None = None
    last_synced_at: datetime | None = None


class LauncherDashboardActivityItemRead(BaseModel):
    id: UUID
    event_type: str
    message: str | None = None
    created_at: datetime


class LauncherDashboardRead(BaseModel):
    nation: LauncherDashboardNationRead | None = None
    nation_stats: NationStatsRead | None = None
    player_stats: LauncherDashboardPlayerStatsRead | None = None
    recent_activity: list[LauncherDashboardActivityItemRead] = Field(default_factory=list)
    wallet_balance: float = 0
