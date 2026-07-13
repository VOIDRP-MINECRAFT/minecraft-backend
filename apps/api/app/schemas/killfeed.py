from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Game-facing (mod → backend, X-Game-Auth-Secret) ──────────────────────────

class KillEventIngest(BaseModel):
    killer_nick: str
    victim_nick: str
    weapon: str | None = None
    kind: str = "pvp"


class KillEventIngestResponse(BaseModel):
    ok: bool = True


# ── Public (site killfeed) ───────────────────────────────────────────────────

class KillEventRead(BaseModel):
    kind: str
    killer_nick: str
    victim_nick: str
    weapon: str | None = None
    created_at: datetime


class KillfeedResponse(BaseModel):
    events: list[KillEventRead] = Field(default_factory=list)
