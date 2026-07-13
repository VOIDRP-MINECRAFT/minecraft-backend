from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Game-facing (mod ↔ backend, X-Game-Auth-Secret) ──────────────────────────

class BountyPlaceRequest(BaseModel):
    target_nick: str
    placed_by_nick: str
    amount: int = Field(gt=0)
    # "player" (diamonds escrowed by the mod) or "server" (notoriety auto-bounty).
    source: str = "player"


class BountyClaimRequest(BaseModel):
    target_nick: str
    killer_nick: str


class BountyActionResponse(BaseModel):
    ok: bool
    error: str | None = None
    # Total diamonds pledged on the target after this action (place: new open sum;
    # claim: amount the killer should be given, then reset to 0).
    total_amount: int = 0


# ── Read (board — game list + public site) ───────────────────────────────────

class BountyBoardEntry(BaseModel):
    target_nick: str
    total_amount: int
    contributor_count: int
    last_updated: datetime
    # True if any part of the pledge is a server-funded "wanted" (notoriety) bounty.
    is_wanted: bool = False


class BountyBoardResponse(BaseModel):
    bounties: list[BountyBoardEntry] = Field(default_factory=list)
