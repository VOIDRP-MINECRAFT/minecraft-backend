from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PlayerTopEntry(BaseModel):
    rank: int
    minecraft_nickname: str
    value: float
    last_seen_at: datetime | None = None


class PlayerTopCategory(BaseModel):
    key: str
    label: str
    unit: str
    entries: list[PlayerTopEntry]


class PlayerTopResponse(BaseModel):
    categories: list[PlayerTopCategory]
