"""Admin: plugins of the selected server, and the queue of mod/plugin jar changes it
shares with the mods section (see core/server_changes.py).

/admin/plugins — list (plugin.yml of each jar), upload to staging and see what each jar
would do, queue the chosen ones, switch off/on, remove.
/admin/server-changes — what is queued, cancel one, "restart and apply" (a job for the
worker: warn players, stop, swap the jars, start).
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import mod_ops, plugin_ops, server_changes
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_any_permission, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_change import ServerFileChange, ServerRestartJob
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/plugins", tags=["admin", "plugins"],
                   dependencies=[Depends(require_permission("plugins.view"))])
changes_router = APIRouter(prefix="/admin/server-changes", tags=["admin", "plugins", "mods"],
                           dependencies=[Depends(require_any_permission("mods.view", "plugins.view"))])
_MANAGE = Depends(require_permission("plugins.manage"))


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _audit(session: Session, actor: User, server: GameServer, action: str, target: str, **meta) -> None:
    record_audit(session, actor=actor, category="plugins", action=action, target_type="plugin",
                 target_id=target[:120], target_label=target, server_id=server.id, meta=meta or None)


@router.get("")
def list_plugins(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    return plugin_ops.list_plugins(session, server)


@router.post("/upload", dependencies=[_MANAGE])
async def upload(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    files: list[UploadFile] = File(...),
) -> dict:
    payload = []
    for f in files:
        data = await f.read(mod_ops._MAX_JAR_BYTES + 1)
        if len(data) > mod_ops._MAX_JAR_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename}: больше 300 МБ")
        payload.append((f.filename or "", data))
    try:
        return plugin_ops.stage(session, server, payload)
    except mod_ops.ModOpsError as exc:
        raise _fail(exc)


class ApplyRequest(BaseModel):
    token: str
    filenames: list[str] = Field(min_length=1)


@router.post("/apply", dependencies=[_MANAGE])
def apply(
    req: ApplyRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    try:
        result = plugin_ops.apply_staged(session, server, req.token, req.filenames, actor.site_login)
    except (mod_ops.ModOpsError, server_changes.ChangeError) as exc:
        raise _fail(exc)
    for q in result["queued"]:
        _audit(session, actor, server, "upload", q["filename"], label=q["label"], status=q["status"])
    return result


class ToggleRequest(BaseModel):
    op: str  # disable | enable | remove


@router.post("/{filename}/change", dependencies=[_MANAGE])
def change(
    filename: str,
    req: ToggleRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    if req.op not in ("disable", "enable", "remove"):
        raise HTTPException(status_code=400, detail="Неизвестное действие")
    words = {"disable": "выключить", "enable": "включить", "remove": "удалить"}
    try:
        c = server_changes.queue(session, server, kind="plugin", op=req.op, filename=filename,
                                 label=f"{words[req.op]} {filename}", created_by=actor.site_login)
    except (mod_ops.ModOpsError, server_changes.ChangeError) as exc:
        raise _fail(exc)
    _audit(session, actor, server, req.op, filename, status=c.status)
    return {"status": c.status, "result": c.result}


# ── The queue ────────────────────────────────────────────────────────────────

def _change_out(c: ServerFileChange) -> dict:
    return {"id": str(c.id), "kind": c.kind, "op": c.op, "filename": c.filename, "replaces": c.replaces,
            "label": c.label, "status": c.status, "result": c.result, "created_by": c.created_by,
            "created_at": c.created_at.isoformat(), "applied_at": c.applied_at.isoformat() if c.applied_at else None}


def _job_out(j: ServerRestartJob | None) -> dict | None:
    if j is None:
        return None
    return {"id": str(j.id), "status": j.status, "step": j.step, "error": j.error, "requested_by": j.requested_by,
            "created_at": j.created_at.isoformat(), "finished_at": j.finished_at.isoformat() if j.finished_at else None}


@changes_router.get("")
def list_changes(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    pending = server_changes.pending(session, server)
    recent = (session.query(ServerFileChange)
              .filter(ServerFileChange.server_id == server.id, ServerFileChange.status != "pending")
              .order_by(ServerFileChange.updated_at.desc()).limit(15).all())
    job = (session.query(ServerRestartJob).filter(ServerRestartJob.server_id == server.id)
           .order_by(ServerRestartJob.created_at.desc()).first())
    return {"pending": [_change_out(c) for c in pending], "recent": [_change_out(c) for c in recent],
            "job": _job_out(job), "running": server_changes.running(server),
            "can_restart": bool(server.systemd_unit and server.rcon_port)}


@changes_router.delete("/{change_id}", dependencies=[Depends(require_any_permission("mods.manage", "plugins.manage"))])
def cancel_change(
    change_id: UUID,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    c = session.get(ServerFileChange, change_id)
    if c is None or c.server_id != server.id or c.status != "pending":
        raise HTTPException(status_code=404, detail="Изменение не найдено в очереди")
    server_changes.cancel(session, c)
    record_audit(session, actor=actor, category="plugins" if c.kind == "plugin" else "mods", action="cancel_change",
                 target_type="file", target_id=c.filename, target_label=c.label, server_id=server.id)
    return {"ok": True}


class RestartRequest(BaseModel):
    warn_seconds: int = Field(default=30, ge=0, le=300)


@changes_router.post("/apply-now", dependencies=[Depends(require_any_permission("mods.manage", "plugins.manage"))])
def apply_now(
    req: RestartRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    """Applies the queue: at once if the server is stopped, otherwise a restart job."""
    if not server_changes.pending(session, server):
        raise HTTPException(status_code=400, detail="Очередь пуста — применять нечего")
    if not server_changes.running(server):
        applied = server_changes.apply_pending(session, server)
        return {"applied_now": [_change_out(c) for c in applied]}
    if session.query(ServerRestartJob).filter(ServerRestartJob.server_id == server.id,
                                              ServerRestartJob.status.in_(("pending", "running"))).first():
        raise HTTPException(status_code=409, detail="Перезапуск уже идёт")
    if not (server.systemd_unit and server.rcon_port):
        raise HTTPException(status_code=409, detail="Для перезапуска у сервера должны быть заданы systemd-юнит и RCON")
    job = ServerRestartJob(server_id=server.id, status="pending", step="Ждёт исполнителя (до минуты)",
                           warn_seconds=req.warn_seconds, requested_by=actor.site_login)
    session.add(job)
    session.commit()
    record_audit(session, actor=actor, category="plugins", action="restart_apply", target_type="server",
                 target_id=server.slug, target_label=server.name, server_id=server.id,
                 meta={"pending": len(server_changes.pending(session, server)), "warn_seconds": req.warn_seconds})
    return {"job": _job_out(job)}
