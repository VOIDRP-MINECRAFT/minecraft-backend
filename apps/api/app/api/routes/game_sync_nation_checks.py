"""Checks that a nation's in-game data still matches reality, with a HUD notice to the leader.

The FTB claims exporter (scripts/update_bluemap_ftb_claims.py) posts the centre of every nation's
claimed land here every few minutes. Capitals are marked by hand with /nsetcapital, so they go stale
when a nation moves or when the world they were set in leaves the pack.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.nation import Nation
from apps.api.app.models.player_notification import PlayerNotification
from apps.api.app.services.notification_service import NotificationService

router = APIRouter(prefix="/game-sync/nations", tags=["game-sync", "nations"])

# Farther than this from the centre of the main claimed area, a capital no longer points at the nation.
CAPITAL_MAX_DISTANCE = 1000
# A nation with a real piece of land (not a single test claim) should have a capital.
CAPITAL_MISSING_MIN_CHUNKS = 16
# Repeat a reminder while the problem is still there, but not more often than this.
REMIND_EVERY = timedelta(hours=72)
NOTICE_TYPE = "nation_capital"


class TerritoryEntry(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    world: str = Field(min_length=1, max_length=64)
    center_x: int
    center_z: int
    chunks: int = Field(ge=0)


class TerritoryCheckRequest(BaseModel):
    nations: list[TerritoryEntry] = Field(default_factory=list, max_length=2000)


def _issue(nation: Nation, area: TerritoryEntry) -> tuple[str, str] | None:
    if nation.capital_world is None or nation.capital_x is None or nation.capital_z is None:
        if area.chunks < CAPITAL_MISSING_MIN_CHUNKS:
            return None
        return (
            "Отметьте столицу государства",
            f"У «{nation.title}» есть земли, но столица не отмечена. Встаньте в центре своей территории "
            "и введите /nsetcapital — за первую столицу казна получит 50 000.",
        )
    if nation.capital_world != area.world:
        return (
            "Смените столицу — там старая информация",
            f"Столица «{nation.title}» отмечена в мире «{nation.capital_world}», а ваши земли в другом мире. "
            "Встаньте на своей территории и введите /nsetcapital.",
        )
    distance = math.hypot(nation.capital_x - area.center_x, nation.capital_z - area.center_z)
    if distance > CAPITAL_MAX_DISTANCE:
        return (
            "Смените столицу — там старая информация",
            f"Столица «{nation.title}» отмечена в {round(distance):,} блоках от ваших земель ".replace(",", " ")
            + f"(X {nation.capital_x}, Z {nation.capital_z}). Встаньте на своей территории и введите /nsetcapital.",
        )
    return None


@router.post("/territory-check")
def territory_check(
    payload: TerritoryCheckRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    areas = {a.slug: a for a in payload.nations}
    if not areas:
        return {"checked": 0, "notified": []}
    nations = db.execute(
        select(Nation).where(Nation.server_id == server.id, Nation.slug.in_(list(areas)), Nation.is_technical.is_(False))
    ).scalars().all()

    notices = NotificationService(db, server.id)
    since = datetime.now(timezone.utc) - REMIND_EVERY
    notified: list[str] = []
    for nation in nations:
        issue = _issue(nation, areas[nation.slug])
        if issue is None:
            continue
        recent = db.execute(
            select(PlayerNotification.id).where(
                PlayerNotification.server_id == server.id,
                PlayerNotification.user_id == nation.leader_user_id,
                PlayerNotification.type == NOTICE_TYPE,
                PlayerNotification.created_at >= since,
            ).limit(1)
        ).scalar_one_or_none()
        if recent is not None:
            continue
        title, body = issue
        notices.create(
            user_id=nation.leader_user_id,
            type=NOTICE_TYPE,
            title=title,
            body=body,
            icon="map",
            accent="gold",
        )
        notified.append(nation.slug)
    db.commit()
    return {"checked": len(nations), "notified": notified}
