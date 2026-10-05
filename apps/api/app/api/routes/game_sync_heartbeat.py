"""Heartbeat of our plugins on a game server — see core/server_reports.py."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import integration_history, integration_updates, server_status
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_report import ServerPluginReport

router = APIRouter(prefix="/game-sync", tags=["game-sync"])


class ModuleState(BaseModel):
    ok: bool
    detail: str | None = Field(default=None, max_length=300)


class Heartbeat(BaseModel):
    plugin: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    version: str | None = Field(default=None, max_length=32)
    core: str | None = Field(default=None, max_length=160)
    modules: dict[str, ModuleState] = Field(default_factory=dict, max_length=32)
    # Monitoring numbers: tps, mspt, online, max, players, memory_used_mb, memory_max_mb, uptime_s.
    data: dict[str, Any] = Field(default_factory=dict)
    # VoidRpPerms 0.6.0+, every ten minutes: plugins, Java, server.properties (integration_updates).
    inventory: dict[str, Any] | None = None


def _clean_data(data: dict[str, Any]) -> dict[str, Any]:
    """Keeps the known monitoring fields with sane types; a heartbeat is not a free-form store."""
    out: dict[str, Any] = {}
    for key in ("tps", "mspt"):
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = round(float(v), 2)
    for key in ("online", "max", "memory_used_mb", "memory_max_mb", "uptime_s"):
        v = data.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[key] = v
    # What the plugin's side of the API understands (integration_updates.FEATURES).
    proto = data.get("protocol")
    if isinstance(proto, int) and not isinstance(proto, bool) and 0 <= proto < 1000:
        out["protocol"] = proto
    players = data.get("players")
    if isinstance(players, list):
        out["players"] = [str(p)[:32] for p in players[:500]]
    return out


@router.post("/heartbeat")
def heartbeat(
    body: Heartbeat,
    server: Annotated[GameServer, Depends(require_game_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    report = session.get(ServerPluginReport, (server.id, body.plugin))
    first = report is None
    if report is None:
        report = ServerPluginReport(server_id=server.id, plugin=body.plugin)
        session.add(report)
    old_version, old_modules = report.version, dict(report.modules or {})
    report.version = body.version
    report.core = body.core
    report.modules = {k[:32]: v.model_dump() for k, v in body.modules.items()}
    integration_history.on_heartbeat(session, server, body.plugin, old_version, body.version,
                                     old_modules, report.modules, first)
    if first or old_version != body.version:
        integration_history.trim(session, server)
    report.data = _clean_data(body.data)
    report.reported_at = utc_now()
    session.commit()
    if body.inventory:
        integration_updates.store_inventory(server, body.inventory)
    server_status.record_heartbeat(session, server, report)
    session.commit()
    answer: dict[str, Any] = {"ok": True, "server": server.slug}
    # Still on the secret before a smooth rotation: VoidRpPerms 0.6.2+ takes the new one from
    # here and rewrites the configs of our plugins; the page lists who has not moved yet.
    if getattr(server, "_used_previous_secret", False):
        integration_updates.mark_old_secret(server, body.plugin)
        if integration_updates.supports(report, "new_secret"):
            answer["new_secret"] = server.game_auth_secret
    if integration_updates.supports(report, "updates"):
        # Updates the owner turned on in «Интеграция»: VoidRpPerms puts them in the update folder.
        answer.update(integration_updates.updates_for(session, server))
    if integration_updates.supports(report, "notices"):
        answer["notices"] = integration_updates.op_notices(session, server)
    if integration_updates.supports(report, "restart"):
        window = integration_updates.restart_window(server)
        if window:
            answer["restart"] = window
    return answer
