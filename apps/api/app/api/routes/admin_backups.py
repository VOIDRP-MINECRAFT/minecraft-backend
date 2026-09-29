"""Admin: backups of the selected server's worlds — list, make one now, restore, delete,
and the schedule.

Nothing heavy happens here: making and restoring backups is the worker's job
(``apps/worker/backups.py``, from cron every minute), so these endpoints only queue it
and report how it is going. Deleting is the exception — removing a file is quick.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission, require_reauth
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_backup import (
    ServerBackup,
    ServerBackupRestore,
    ServerBackupSettings,
    default_backup_settings,
)
from apps.api.app.models.user import User
from apps.api.app.services import backups as svc

router = APIRouter(
    prefix="/admin/backups",
    tags=["admin", "backups"],
    dependencies=[Depends(require_permission("backups.view"))],
)

_ACTIVE = ("pending", "running")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _backup_out(b: ServerBackup) -> dict:
    return {
        "id": str(b.id), "kind": b.kind, "status": b.status, "note": b.note,
        "size_bytes": b.size_bytes, "worlds": b.worlds or [], "error": b.error, "progress": b.progress,
        "created_by": b.created_by, "created_at": _iso(b.created_at),
        "started_at": _iso(b.started_at), "finished_at": _iso(b.finished_at),
        "file_present": bool(b.path and os.path.isfile(b.path)),
    }


def _restore_out(r: ServerBackupRestore) -> dict:
    return {
        "id": str(r.id), "backup_id": str(r.backup_id), "status": r.status, "step": r.step, "error": r.error,
        "pre_backup_id": str(r.pre_backup_id) if r.pre_backup_id else None,
        "requested_by": r.requested_by, "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
    }


def _settings(session: Session, server: GameServer) -> ServerBackupSettings | None:
    return session.query(ServerBackupSettings).filter(ServerBackupSettings.server_id == server.id).one_or_none()


def _readiness(server: GameServer) -> dict:
    """What the worker needs to back this server up and restore it, and what is missing."""
    data_dir = server_ops.resolve_data_dir(server)
    worlds = svc.world_folders(data_dir) if data_dir else []
    problems = []
    if not data_dir or not os.path.isdir(data_dir):
        problems.append("Не найдена папка сервера: задайте systemd-юнит или data_dir в «Серверах».")
    elif not worlds:
        problems.append("В папке сервера нет миров (папок с level.dat).")
    if not server.rcon_port or server.rcon_password is None:
        problems.append("Не настроен RCON — без него мир нельзя сохранить перед бэкапом.")
    if not server.systemd_unit:
        problems.append("Не задан systemd-юнит — откат не сможет дождаться перезапуска сервера.")
    return {"data_dir": data_dir, "worlds": worlds, "problems": problems}


@router.get("")
def list_backups(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    backups = (
        session.query(ServerBackup).filter(ServerBackup.server_id == server.id)
        .order_by(ServerBackup.created_at.desc()).limit(200).all()
    )
    restores = (
        session.query(ServerBackupRestore).filter(ServerBackupRestore.server_id == server.id)
        .order_by(ServerBackupRestore.created_at.desc()).limit(10).all()
    )
    settings = _settings(session, server)
    config = {**default_backup_settings(), **(settings.config if settings else {})}
    last_scheduled = next((b for b in backups if b.kind == "scheduled" and b.status == "done"), None)
    return {
        "items": [_backup_out(b) for b in backups],
        "restores": [_restore_out(r) for r in restores],
        "settings": config,
        "settings_updated_by": settings.updated_by if settings else None,
        "last_scheduled_at": _iso(last_scheduled.created_at) if last_scheduled else None,
        "storage": {"dir": str(svc.archive_dir(server.slug)), **(svc.disk_usage(svc.BACKUP_ROOT) or {})},
        "server": _readiness(server),
    }


class CreateBackupRequest(BaseModel):
    note: str = Field(default="", max_length=256)


@router.post("", dependencies=[Depends(require_permission("backups.create"))])
def create_backup(
    req: CreateBackupRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    ready = _readiness(server)
    if ready["problems"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ready["problems"][0])
    busy = session.query(ServerBackup).filter(
        ServerBackup.server_id == server.id, ServerBackup.status.in_(_ACTIVE)
    ).first()
    if busy is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A backup of this server is already being made")
    backup = ServerBackup(
        server_id=server.id, kind="manual", status="pending", note=req.note.strip() or None,
        worlds=[], created_by=actor.site_login,
    )
    session.add(backup)
    session.commit()
    record_audit(session, actor=actor, category="backups", action="create", target_type="backup",
                 target_id=str(backup.id), target_label=req.note or None, server_id=server.id)
    return _backup_out(backup)


class RestoreRequest(BaseModel):
    # How long players are warned in chat before the server stops.
    warn_seconds: int = Field(default=30, ge=0, le=300)


@router.post("/{backup_id}/restore", dependencies=[Depends(require_permission("backups.restore")), Depends(require_reauth)])
def restore_backup(
    backup_id: UUID,
    req: RestoreRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    backup = session.get(ServerBackup, backup_id)
    if backup is None or backup.server_id != server.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    if backup.status != "done" or not backup.path or not os.path.isfile(backup.path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This backup is not ready or its file is missing")
    ready = _readiness(server)
    if ready["problems"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ready["problems"][0])
    if session.query(ServerBackupRestore).filter(
        ServerBackupRestore.server_id == server.id, ServerBackupRestore.status.in_(_ACTIVE)
    ).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A restore of this server is already in progress")
    restore = ServerBackupRestore(
        server_id=server.id, backup_id=backup.id, status="pending", step="Ждёт исполнителя (до минуты)",
        warn_seconds=req.warn_seconds, requested_by=actor.site_login,
    )
    session.add(restore)
    session.commit()
    record_audit(session, actor=actor, category="backups", action="restore", target_type="backup",
                 target_id=str(backup.id), target_label=_iso(backup.created_at), server_id=server.id,
                 meta={"warn_seconds": req.warn_seconds})
    return _restore_out(restore)


@router.delete("/{backup_id}", dependencies=[Depends(require_permission("backups.delete")), Depends(require_reauth)])
def delete_backup(
    backup_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    backup = session.get(ServerBackup, backup_id)
    if backup is None or backup.server_id != server.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    if backup.status in _ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This backup is still being made")
    if session.query(ServerBackupRestore).filter(
        ServerBackupRestore.backup_id == backup.id, ServerBackupRestore.status.in_(_ACTIVE)
    ).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The server is being restored from this backup")
    if backup.path and os.path.isfile(backup.path):
        if not svc.within_backup_root(backup.path):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The backup file is outside the backup folder")
        os.remove(backup.path)
    label = _iso(backup.created_at)
    session.delete(backup)
    session.commit()
    record_audit(session, actor=actor, category="backups", action="delete", target_type="backup",
                 target_id=str(backup_id), target_label=label, server_id=server.id)
    return {"ok": True}


class SettingsRequest(BaseModel):
    enabled: bool
    every_hours: int = Field(ge=1, le=168)
    keep: int = Field(ge=1, le=100)


@router.put("/settings", dependencies=[Depends(require_permission("backups.settings"))])
def update_settings(
    req: SettingsRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    row = _settings(session, server)
    config = {"enabled": req.enabled, "every_hours": req.every_hours, "keep": req.keep}
    if row is None:
        row = ServerBackupSettings(server_id=server.id, config=config)
        session.add(row)
    else:
        row.config = config
    row.updated_by = actor.site_login
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    record_audit(session, actor=actor, category="backups", action="settings", target_type="server",
                 target_id=str(server.id), target_label=server.slug, server_id=server.id, meta=config)
    return {"settings": config, "settings_updated_by": row.updated_by}
