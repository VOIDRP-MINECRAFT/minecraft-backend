from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class IssuePlayTicketRequest(BaseModel):
    launcher_version: str = Field(default="unknown", min_length=1, max_length=32)
    launcher_platform: str = Field(default="unknown", min_length=1, max_length=64)


class IssuePlayTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime
    minecraft_nickname: str
    ttl_seconds: int
    # On plugin servers the launcher connects the game to
    # "<hostname_label>.<server host>" so a vanilla client carries the ticket.
    hostname_label: str | None = None


class ConsumePlayTicketRequest(BaseModel):
    ticket: str = Field(min_length=16, max_length=512)
    player_name: str = Field(min_length=3, max_length=16)
    launcher_proof: str | None = None


class ConsumePlayTicketResponse(BaseModel):
    accepted: bool = True
    user_id: UUID
    minecraft_nickname: str
    legacy_auth_enabled: bool
    expires_at: datetime
