"""The queue of jar changes to a server's mods and plugins (see models/server_change.py).

``queue()`` applies a change at once when the server is stopped — nothing is reading
the jars then — and otherwise keeps it until the server is down: the restart job
("Перезапустить и применить", run by apps/worker/backups.py), or the worker finding
the server stopped. Nothing is ever deleted outright: a removed or replaced jar goes to
the same timestamped trash the mods section uses.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.app.core import mod_ops, server_ops
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_change import ServerFileChange

PENDING_BASE = os.path.join(mod_ops.OPS_BASE, "pending")


class ChangeError(Exception):
    pass


def running(server: GameServer) -> bool:
    if not server.systemd_unit:
        return False
    props = server_ops._systemctl_props(server.systemd_unit, ("ActiveState", "MainPID"))
    return int(props.get("MainPID") or 0) > 0


def folder(server: GameServer, kind: str) -> str:
    data_dir = server_ops.resolve_data_dir(server)
    if not data_dir or not os.path.isdir(data_dir):
        raise ChangeError("У сервера нет папки на этой машине")
    return mod_ops.server_mods_dir(server) if kind == "mod" else os.path.join(data_dir, "plugins")


def keep_source(server: GameServer, src_path: str, filename: str) -> str:
    """A copy of a staged jar that lives until its change is applied or cancelled."""
    d = os.path.join(PENDING_BASE, server.slug)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{uuid.uuid4().hex[:12]}-{filename}")
    shutil.copy2(src_path, dest)
    return dest


def queue(session: Session, server: GameServer, *, kind: str, op: str, filename: str,
          source_path: str | None = None, replaces: str | None = None, label: str | None = None,
          created_by: str | None = None) -> ServerFileChange:
    filename = mod_ops.sanitize_jar(filename)
    if replaces:
        replaces = mod_ops.sanitize_jar(replaces)
    # One pending change per file: a newer request takes the place of an older one.
    for old in session.query(ServerFileChange).filter(
        ServerFileChange.server_id == server.id, ServerFileChange.kind == kind,
        ServerFileChange.status == "pending", ServerFileChange.filename == filename,
    ).all():
        cancel(session, old, commit=False)
    change = ServerFileChange(server_id=server.id, kind=kind, op=op, filename=filename, source_path=source_path,
                              replaces=replaces, label=label, status="pending", created_by=created_by)
    session.add(change)
    session.commit()
    if not running(server):
        apply_one(session, server, change)
    return change


def cancel(session: Session, change: ServerFileChange, commit: bool = True) -> None:
    if change.status != "pending":
        return
    change.status = "cancelled"
    if change.source_path and os.path.isfile(change.source_path):
        os.remove(change.source_path)
    if commit:
        session.commit()


def apply_one(session: Session, server: GameServer, change: ServerFileChange) -> None:
    """Carries out one change. The caller makes sure the server is not running."""
    side = "server" if change.kind == "mod" else "plugins"
    try:
        base = folder(server, change.kind)
        os.makedirs(base, exist_ok=True)
        target = os.path.join(base, change.filename)
        disabled_dir = os.path.join(base, "disabled")
        if change.op == "add":
            if not change.source_path or not os.path.isfile(change.source_path):
                raise ChangeError("Загруженный файл пропал — загрузите заново")
            if change.replaces and change.replaces != change.filename:
                for old in (os.path.join(base, change.replaces), os.path.join(disabled_dir, change.replaces)):
                    if os.path.isfile(old):
                        mod_ops._trash(server.slug, side, old)
            elif os.path.isfile(target):
                mod_ops._trash(server.slug, side, target)
            mod_ops._atomic_copy(change.source_path, target)
            os.remove(change.source_path)
            result = f"Установлен {change.filename}" + (f" вместо {change.replaces}" if change.replaces and change.replaces != change.filename else "")
        elif change.op == "remove":
            found = [p for p in (target, os.path.join(disabled_dir, change.filename)) if os.path.isfile(p)]
            if not found:
                raise ChangeError(f"{change.filename} уже нет")
            for p in found:
                mod_ops._trash(server.slug, side, p)
            result = f"Удалён {change.filename} (лежит в корзине)"
        elif change.op == "disable":
            if not os.path.isfile(target):
                raise ChangeError(f"{change.filename} не найден среди включённых")
            os.makedirs(disabled_dir, exist_ok=True)
            os.replace(target, os.path.join(disabled_dir, change.filename))
            result = f"Выключен {change.filename}"
        elif change.op == "enable":
            src = os.path.join(disabled_dir, change.filename)
            if not os.path.isfile(src):
                raise ChangeError(f"{change.filename} не найден среди выключенных")
            os.replace(src, target)
            result = f"Включён {change.filename}"
        else:
            raise ChangeError(f"Неизвестное действие: {change.op}")
        change.status = "applied"
        change.result = result
    except (ChangeError, mod_ops.ModOpsError, OSError) as exc:
        change.status = "failed"
        change.result = str(exc)
    change.applied_at = datetime.now(timezone.utc)
    session.commit()


def pending(session: Session, server: GameServer) -> list[ServerFileChange]:
    return (session.query(ServerFileChange)
            .filter(ServerFileChange.server_id == server.id, ServerFileChange.status == "pending")
            .order_by(ServerFileChange.created_at).all())


def apply_pending(session: Session, server: GameServer) -> list[ServerFileChange]:
    changes = pending(session, server)
    for change in changes:
        apply_one(session, server, change)
    return changes
