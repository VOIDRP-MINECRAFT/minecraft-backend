from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NationActivityActorRead(BaseModel):
    user_id: UUID | None = None
    site_login: str | None = None
    minecraft_nickname: str | None = None


class NationActivityLogRead(BaseModel):
    id: UUID
    nation_id: UUID
    event_type: str
    message: str | None = None
    metadata: dict[str, object] = {}
    actor: NationActivityActorRead | None = None
    target: NationActivityActorRead | None = None
    created_at: datetime


class NationActivityLogListResponse(BaseModel):
    total: int
    items: list[NationActivityLogRead]
