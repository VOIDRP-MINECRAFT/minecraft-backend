"""The VoidRpPerms plugin's side: it reports the LuckPerms catalog, takes queued changes
and reports their results. Authenticated as the game server (X-Game-Auth-Secret)."""
from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import game_perms
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_perm import GamePermCatalog, GamePermOp
from apps.api.app.models.game_server import GameServer

router = APIRouter(prefix="/game-sync/perms", tags=["game-sync", "game-perms"])

_Server = Annotated[GameServer, Depends(require_game_server)]
_Db = Annotated[Session, Depends(get_db_session)]


@router.post("/catalog")
def push_catalog(body: dict[str, Any], server: _Server, session: _Db) -> dict:
    row = session.get(GamePermCatalog, server.id)
    data = {"groups": body.get("groups") or [], "permissions": body.get("permissions") or []}
    if row is None:
        session.add(GamePermCatalog(server_id=server.id, data=data, plugin_version=body.get("plugin_version")))
    else:
        row.data = data
        row.plugin_version = body.get("plugin_version")
        row.updated_at = utc_now()
    session.commit()
    return {"ok": True}


@router.get("/ops")
def pending_ops(server: _Server, session: _Db) -> list[dict]:
    """Pending changes, oldest first — after a fresh reconcile, so role changes made while
    the plugin was away are caught up."""
    game_perms.reconcile(session, server.id)
    session.commit()
    rows = session.scalars(select(GamePermOp).where(GamePermOp.server_id == server.id, GamePermOp.status == "pending")
                           .order_by(GamePermOp.created_at).limit(50)).all()
    return [{"id": str(r.id), **r.op} for r in rows]


class OpResult(BaseModel):
    ok: bool
    result: str | None = None


@router.post("/ops/{op_id}/result")
def op_result(op_id: UUID, body: OpResult, server: _Server, session: _Db) -> dict:
    op = session.get(GamePermOp, op_id)
    if op is None or op.server_id != server.id:
        raise HTTPException(status_code=404, detail="op not found")
    if op.status == "pending":
        game_perms.record_result(session, op, body.ok, body.result)
        session.commit()
    return {"ok": True}
