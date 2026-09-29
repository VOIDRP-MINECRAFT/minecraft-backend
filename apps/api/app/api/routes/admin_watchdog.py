"""Admin: the selected server's hang watchdog — its thresholds, what it sees, what it did.

Shown in the Monitoring page's "Присмотр за сервером" card. Whether it is on is the
card's existing "Сторож зависаний" switch (``voidrp-watchdog.json`` in the server's
folder, see server_ops.get_watchdog_state): for the main server the scripts read it, for
every other server ``apps/worker/watchdog.py`` does. This stores the rest.
"""
from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_watchdog import ServerWatchdog, ServerWatchdogEvent, default_watchdog
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/watchdog",
    tags=["admin", "watchdog"],
    dependencies=[Depends(require_permission("monitoring.view"))],
)

def _row(session: Session, server: GameServer) -> ServerWatchdog | None:
    return session.query(ServerWatchdog).filter(ServerWatchdog.server_id == server.id).one_or_none()


@router.get("")
def overview(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    row = _row(session, server)
    events = (
        session.query(ServerWatchdogEvent).filter(ServerWatchdogEvent.server_id == server.id)
        .order_by(ServerWatchdogEvent.created_at.desc()).limit(50).all()
    )
    unit = {}
    if server.systemd_unit:
        unit = server_ops._systemctl_props(server.systemd_unit, ("ActiveState", "SubState", "MainPID"))
    data_dir = server_ops.resolve_data_dir(server)
    problems = []
    if not server.systemd_unit:
        problems.append("Не задан systemd-юнит — вотчдог не знает, какой процесс смотреть.")
    if not server.rcon_port or server.rcon_password is None:
        problems.append("Не настроен RCON — вотчдог не может спросить сервер, отвечает ли он.")
    switch = server_ops.get_watchdog_state(server)
    return {
        "settings": {k: v for k, v in {**default_watchdog(), **(row.config if row else {})}.items() if k != "enabled"},
        "switch": {"available": switch.get("available", False), "enabled": switch.get("enabled"),
                   "effective": switch.get("effective")},
        "settings_updated_by": row.updated_by if row else None,
        "state": (row.state if row else {}) or {},
        "unit": {"name": server.systemd_unit, "active": unit.get("ActiveState"), "sub": unit.get("SubState"),
                 "pid": int(unit.get("MainPID") or 0)},
        "maintenance": bool(data_dir and os.path.exists(os.path.join(data_dir, "maintenance.flag"))),
        "problems": problems,
        "events": [
            {"id": str(e.id), "kind": e.kind, "detail": e.detail, "dump_path": e.dump_path, "at": e.created_at.isoformat()}
            for e in events
        ],
    }


class WatchdogSettings(BaseModel):
    hang_minutes: int = Field(ge=1, le=60)
    startup_grace_minutes: int = Field(ge=1, le=60)
    action: Literal["restart", "notify"]
    max_restarts_per_hour: int = Field(ge=1, le=20)
    own_script: bool = False


@router.put("/settings", dependencies=[Depends(require_permission("monitoring.restart"))])
def update(
    req: WatchdogSettings,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    row = _row(session, server)
    config = req.model_dump()  # the on/off switch is the Monitoring card's, not stored here
    if row is None:
        row = ServerWatchdog(server_id=server.id, config=config, state={})
        session.add(row)
    else:
        row.config = config
    row.updated_by = actor.site_login
    session.commit()
    record_audit(session, actor=actor, category="watchdog", action="settings", target_type="server",
                 target_id=str(server.id), target_label=server.slug, server_id=server.id, meta=config)
    return {"settings": config, "settings_updated_by": row.updated_by}
