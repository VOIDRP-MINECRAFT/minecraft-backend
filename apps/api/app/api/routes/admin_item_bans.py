"""Admin panel: banned items of the server chosen in the panel (docs/item_bans_plan.md).

The game server's plugin fetches the list from /game-sync/item-bans and removes those items
from players; every change here reaches the server within the plugin's poll interval.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import item_catalog
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.item_ban import MESSAGE_MAX, SCAN_PERIOD_BOUNDS, BannedItem, ServerItems
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/item-bans", tags=["admin", "item-bans"],
                   dependencies=[Depends(require_permission("items.bans.view"))])
_manage = [Depends(require_permission("items.bans.manage"))]

_Server = Annotated[GameServer, Depends(resolve_server)]
_Db = Annotated[Session, Depends(get_db_session)]
_Staff = Annotated[User, Depends(get_current_staff_user)]


class BanCreate(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class BanUpdate(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class SettingsUpdate(BaseModel):
    message: str = Field(min_length=1, max_length=MESSAGE_MAX)
    scan_period_ticks: int = Field(ge=SCAN_PERIOD_BOUNDS[0], le=SCAN_PERIOD_BOUNDS[1])


def _state(session: Session, server: GameServer) -> ServerItems | None:
    return session.get(ServerItems, server.id)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _view(ban: BannedItem, info: dict, registry: set[str] | None) -> dict:
    return {
        "id": str(ban.id),
        "item_id": ban.item_id,
        "name": info["name"],
        "icon": info["icon"],
        "reason": ban.reason,
        "enabled": ban.enabled,
        "created_by": ban.created_by,
        "created_at": _iso(ban.created_at),
        "updated_at": _iso(ban.updated_at),
        # None: the server has not reported its items, so it is unknown.
        "on_server": None if registry is None else ban.item_id in registry,
    }


def _registry(state: ServerItems | None) -> set[str] | None:
    return set(state.item_ids) if state is not None and state.items_reported_at else None


@router.get("")
def list_bans(server: _Server, session: _Db) -> dict:
    bans = session.scalars(
        select(BannedItem).where(BannedItem.server_id == server.id).order_by(BannedItem.created_at.desc())
    ).all()
    state = _state(session, server)
    registry = _registry(state)
    info = item_catalog.describe([b.item_id for b in bans])
    return {
        "items": [_view(b, info[b.item_id], registry) for b in bans],
        "settings": server.resolved_item_ban_settings,
        "sync": {
            "bans_fetched_at": _iso(state.bans_fetched_at) if state else None,
            "items_reported_at": _iso(state.items_reported_at) if state else None,
            "registry_size": len(state.item_ids) if state else 0,
            "plugin_version": state.plugin_version if state else None,
        },
    }


@router.get("/search")
def search_items(server: _Server, session: _Db, q: str = Query("", max_length=64),
                 limit: int = Query(60, ge=1, le=200)) -> dict:
    state = _state(session, server)
    registry = _registry(state)
    results = item_catalog.search(q, sorted(registry) if registry is not None else None, limit)
    banned = set(session.scalars(select(BannedItem.item_id).where(BannedItem.server_id == server.id)).all())
    for r in results:
        r["banned"] = r["id"] in banned
    return {"items": results, "verified": registry is not None}


@router.post("", dependencies=_manage)
def add_bans(body: BanCreate, server: _Server, session: _Db, staff: _Staff) -> dict:
    ids: list[str] = []
    for raw in body.item_ids:
        item_id = item_catalog.normalize_item_id(raw)
        if item_id is None:
            raise HTTPException(status_code=400, detail=f"Неверный id предмета: «{raw}». Нужен вид мод:предмет")
        if item_id not in ids:
            ids.append(item_id)
    existing = set(session.scalars(
        select(BannedItem.item_id).where(BannedItem.server_id == server.id, BannedItem.item_id.in_(ids))
    ).all())
    reason = (body.reason or "").strip() or None
    added = [i for i in ids if i not in existing]
    for item_id in added:
        session.add(BannedItem(server_id=server.id, item_id=item_id, reason=reason, enabled=True,
                               created_by=staff.site_login))
    session.commit()
    return {"added": added, "already": sorted(existing)}


@router.patch("/{ban_id}", dependencies=_manage)
def update_ban(ban_id: UUID, body: BanUpdate, server: _Server, session: _Db) -> dict:
    ban = session.get(BannedItem, ban_id)
    if ban is None or ban.server_id != server.id:
        raise HTTPException(status_code=404, detail="Предмет не найден в списке этого сервера")
    fields = body.model_fields_set
    if "reason" in fields:
        ban.reason = (body.reason or "").strip() or None
    if "enabled" in fields and body.enabled is not None:
        ban.enabled = body.enabled
    session.commit()
    registry = _registry(_state(session, server))
    return _view(ban, item_catalog.describe([ban.item_id])[ban.item_id], registry)


@router.delete("/{ban_id}", dependencies=_manage)
def delete_ban(ban_id: UUID, server: _Server, session: _Db) -> dict:
    ban = session.get(BannedItem, ban_id)
    if ban is None or ban.server_id != server.id:
        raise HTTPException(status_code=404, detail="Предмет не найден в списке этого сервера")
    session.delete(ban)
    session.commit()
    return {"ok": True}


@router.put("/settings", dependencies=_manage)
def update_settings(body: SettingsUpdate, server: _Server, session: _Db) -> dict:
    server.item_ban_settings = {"message": body.message.strip(), "scan_period_ticks": body.scan_period_ticks}
    session.commit()
    return server.resolved_item_ban_settings
