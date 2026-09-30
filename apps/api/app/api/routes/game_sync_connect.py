"""Game server side of the plugin-driven console, log and punishments (core/server_console.py).

VoidRpPerms 0.5.0+ polls ``/console/pending`` every couple of seconds: it gets the commands
to run and the revision of the punishments list (to refetch it the moment staff ban or mute
someone). It posts command output, the new lines of its log, and enforces bans and mutes
itself — no RCON, no EssentialsX needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.app.core import server_console
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.punishment import STANDING_TYPES, Punishment
from apps.api.app.models.server_console import ServerCommand

router = APIRouter(prefix="/game-sync", tags=["game-sync"])

_Server = Annotated[GameServer, Depends(require_game_server)]
_Db = Annotated[Session, Depends(get_db_session)]


def _punishments_scope(server: GameServer):
    return or_(Punishment.server_id == server.id, Punishment.server_id.is_(None))


def _punishments_rev(session: Session, server: GameServer) -> str:
    """Changes whenever a ban/mute of this server (or a global one) is issued or lifted."""
    latest = session.scalar(select(func.max(func.greatest(
        Punishment.created_at, func.coalesce(Punishment.revoked_at, Punishment.created_at)))).where(
        _punishments_scope(server)))
    count = session.scalar(select(func.count()).select_from(Punishment).where(
        _punishments_scope(server), Punishment.active.is_(True)))
    return f"{latest.isoformat() if latest else '-'}:{count}"


@router.get("/console/pending")
def console_pending(server: _Server, session: _Db) -> dict:
    rows = server_console.take_pending(session, server)
    return {
        "commands": [{"id": r.id, "command": r.command} for r in rows],
        "punishments_rev": _punishments_rev(session, server),
    }


class CommandResult(BaseModel):
    ok: bool = True
    output: str = Field(default="", max_length=20000)


@router.post("/console/{command_id}/result")
def console_result(command_id: int, body: CommandResult, server: _Server, session: _Db) -> dict:
    row = session.get(ServerCommand, command_id)
    if row is None or row.server_id != server.id:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    row.status = "done" if body.ok else "failed"
    row.output = body.output
    row.done_at = utc_now()
    session.commit()
    return {"ok": True}


class LogBatch(BaseModel):
    lines: list[str] = Field(default_factory=list, max_length=2000)


@router.post("/log")
def ship_log(body: LogBatch, server: _Server, session: _Db) -> dict:
    return {"stored": server_console.append_log(session, server, body.lines)}


@router.get("/punishments")
def punishments(server: _Server, session: _Db) -> dict:
    """Bans and mutes in force on this server (its own and global ones)."""
    now = datetime.now(timezone.utc)
    rows = session.scalars(select(Punishment).where(
        _punishments_scope(server), Punishment.active.is_(True), Punishment.type.in_(STANDING_TYPES),
        or_(Punishment.expires_at.is_(None), Punishment.expires_at > now))).all()
    return {
        "rev": _punishments_rev(session, server),
        "items": [{
            "type": "ban" if p.type in ("ban", "tempban") else "mute",
            "player_name": p.player_name,
            "player_uuid": p.player_uuid,
            "reason": p.reason,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
            "global": p.server_id is None,
        } for p in rows],
    }
