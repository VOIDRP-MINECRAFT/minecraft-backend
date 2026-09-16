"""In-game roadmap ("путеводитель"): progression stages, and what the player has reached.

The roadmap itself is static content (``core/progression_roadmap.json``). A player's
position comes from two signals: unlocked epochs (player_progressions) and key items
the plugin saw in their inventory (player_guide_items).
"""
from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_guide_item import PlayerGuideItem
from apps.api.app.models.player_progression import MAIN_PROGRESSION_TIERS, PlayerProgression

router = APIRouter(prefix="/game-ui/guide", tags=["game-ui", "guide"])
plugin_router = APIRouter(prefix="/game-sync/guide", tags=["guide"])

ROADMAP_PATH = Path(__file__).resolve().parents[2] / "core" / "progression_roadmap.json"


@lru_cache(maxsize=1)
def load_roadmap() -> dict:
    return json.loads(ROADMAP_PATH.read_text(encoding="utf-8"))


def tracked_items() -> list[str]:
    road = load_roadmap()
    out: list[str] = []
    for block in road["stages"] + road["branches"]:
        for step in block["steps"]:
            if step["item"] not in out:
                out.append(step["item"])
    return out


@router.get("/roadmap")
def get_roadmap() -> dict:
    return load_roadmap()


class GuideProgress(BaseModel):
    tiers: list[str] = []
    items: list[str] = []


@router.get("/progress", response_model=GuideProgress)
def get_progress(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> GuideProgress:
    nick = player.minecraft_nickname.strip().lower()
    tiers = set(db.execute(
        select(PlayerProgression.tier_name).where(
            PlayerProgression.server_id == server.id,
            PlayerProgression.minecraft_nickname_normalized == nick,
        )
    ).scalars().all())
    # A later main-line epoch implies the earlier ones (detection only sees gate items).
    reached = [i for i, t in enumerate(MAIN_PROGRESSION_TIERS) if t in tiers]
    if reached:
        tiers.update(MAIN_PROGRESSION_TIERS[: max(reached) + 1])
    items = db.execute(
        select(PlayerGuideItem.item_id).where(
            PlayerGuideItem.server_id == server.id,
            PlayerGuideItem.minecraft_nickname_normalized == nick,
        )
    ).scalars().all()
    return GuideProgress(tiers=sorted(tiers), items=sorted(set(items)))


@plugin_router.get("/tracked-items")
def get_tracked_items(server: Annotated[GameServer, Depends(require_game_server)]) -> dict:
    return {"items": tracked_items()}


class GuideItemsPush(BaseModel):
    minecraft_uuid: str = Field(..., min_length=1, max_length=36)
    minecraft_nickname: str = Field(..., min_length=1, max_length=64)
    items: list[str] = Field(default_factory=list, max_length=200)


@plugin_router.post("/items")
def push_items(
    payload: GuideItemsPush,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    allowed = set(tracked_items())
    items = [i for i in dict.fromkeys(payload.items) if i in allowed]
    if not items:
        return {"stored": 0}
    nick = payload.minecraft_nickname.strip().lower()
    stmt = insert(PlayerGuideItem).values([
        {"id": uuid.uuid4(), "server_id": server.id, "minecraft_nickname_normalized": nick,
         "minecraft_uuid": payload.minecraft_uuid, "item_id": item}
        for item in items
    ]).on_conflict_do_nothing(constraint="uq_player_guide_items_item")
    db.execute(stmt)
    db.commit()
    return {"stored": len(items)}
