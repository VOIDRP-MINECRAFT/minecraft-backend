from __future__ import annotations

from pydantic import BaseModel, Field


class PlayerStatDelta(BaseModel):
    """Incremental stats accumulated by a game mod since its last flush. Values are
    added to the running totals in ``player_stat_cache`` for the calling server."""

    nick: str
    pvp_kills: int = 0
    mob_kills: int = 0
    deaths: int = 0
    playtime_minutes: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0


class PlayerStatsBatchRequest(BaseModel):
    players: list[PlayerStatDelta] = Field(default_factory=list)


class PlayerStatsBatchResponse(BaseModel):
    ok: bool = True
    updated: int = 0
