"""Game server side of banned items: the plugin takes the list and reports its item registry.

The server is resolved from its own ``X-Game-Auth-Secret``. Taking the list stamps
``server_items.bans_fetched_at``, so the admin page shows whether bans work on that server.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import item_catalog
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.item_ban import BannedItem, ServerItems

router = APIRouter(prefix="/game-sync/item-bans", tags=["game-sync", "item-bans"])

_Server = Annotated[GameServer, Depends(require_game_server)]
_Db = Annotated[Session, Depends(get_db_session)]

# A big modpack registers ~30 000 items; this leaves room without letting a body grow unbounded.
_REGISTRY_MAX = 200_000


class RegistryReport(BaseModel):
    item_ids: list[str] = Field(max_length=_REGISTRY_MAX)
    plugin_version: str | None = Field(default=None, max_length=32)


def _state(session: Session, server: GameServer) -> ServerItems:
    state = session.get(ServerItems, server.id)
    if state is None:
        state = ServerItems(server_id=server.id, item_ids=[])
        session.add(state)
    return state


@router.get("")
def fetch_bans(server: _Server, session: _Db, v: str | None = Query(None, max_length=32)) -> dict:
    ids = session.scalars(
        select(BannedItem.item_id).where(BannedItem.server_id == server.id, BannedItem.enabled.is_(True))
        .order_by(BannedItem.item_id)
    ).all()
    state = _state(session, server)
    state.bans_fetched_at = utc_now()
    if v:
        state.plugin_version = v
    session.commit()
    settings = server.resolved_item_ban_settings
    return {"ids": list(ids), "message": settings["message"], "scan_period_ticks": settings["scan_period_ticks"]}


@router.post("/registry")
def report_registry(body: RegistryReport, server: _Server, session: _Db) -> dict:
    ids = sorted({i for i in (item_catalog.normalize_item_id(x) for x in body.item_ids) if i})
    state = _state(session, server)
    state.item_ids = ids
    state.items_reported_at = utc_now()
    if body.plugin_version:
        state.plugin_version = body.plugin_version
    session.commit()
    return {"stored": len(ids)}
