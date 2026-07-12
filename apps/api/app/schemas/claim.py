from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Game-facing (mod ↔ backend, X-Game-Auth-Secret) ──────────────────────────

class ClaimGameRead(BaseModel):
    """Full claim as the mod needs it for fast in-memory protection checks."""

    id: UUID
    owner_nick: str
    dimension: str
    core_x: int
    core_y: int
    core_z: int
    level: int
    # 16x16x16 cube cells making up the claim volume: [[cx, cy, cz], ...].
    cubes: list[list[int]] = Field(default_factory=list)
    trusted_nicks: list[str] = Field(default_factory=list)


class ClaimListResponse(BaseModel):
    claims: list[ClaimGameRead] = Field(default_factory=list)


class ClaimCreateRequest(BaseModel):
    owner_nick: str
    dimension: str
    core_x: int
    core_y: int
    core_z: int
    level: int = 1


class ClaimUpgradeRequest(BaseModel):
    # The [cx, cy, cz] cube cell to add to the claim (must be adjacent, not taken).
    cube: list[int]


class ClaimTrustRequest(BaseModel):
    nick: str
    action: str  # "add" | "remove"


class ClaimActionResponse(BaseModel):
    ok: bool
    error: str | None = None
    claim: ClaimGameRead | None = None


# ── Site-facing (player cabinet) ─────────────────────────────────────────────

class ClaimSiteRead(BaseModel):
    id: UUID
    dimension: str
    core_x: int
    core_y: int
    core_z: int
    level: int
    size_cubes: int
    cubes: list[list[int]] = Field(default_factory=list)
    trusted_nicks: list[str] = Field(default_factory=list)
    created_at: datetime


class ClaimSiteListResponse(BaseModel):
    claims: list[ClaimSiteRead] = Field(default_factory=list)
