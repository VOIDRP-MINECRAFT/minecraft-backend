"""Reading plugin heartbeats: freshness, required modules, live monitoring numbers.

An external server (a partner's machine) must run the login and monitoring modules before
it is opened to players (docs/external_servers_plan.md). A module counts when some plugin
reported it working within ``FRESH_SECONDS``.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_report import ServerPluginReport

# Plugins beat every 30 s; two missed beats and a bit of slack.
FRESH_SECONDS = 90

# Required on an external server, with what the admin sees.
REQUIRED_MODULES: dict[str, str] = {
    "auth": "Вход через аккаунт VoidRP (VoidRpAuth или voidrp-auth-bridge)",
    "monitoring": "Мониторинг (VoidRpPerms 0.4.0+)",
}

MODULE_LABELS: dict[str, str] = {
    **REQUIRED_MODULES,
    "perms": "Права в игре (LuckPerms из админки)",
    "chat": "Чат с префиксами",
    "anticheat": "Античит VoidRP Guard",
    "item_bans": "Бан предметов",
}


def reports(session: Session, server: GameServer) -> list[ServerPluginReport]:
    return list(session.scalars(
        select(ServerPluginReport).where(ServerPluginReport.server_id == server.id).order_by(ServerPluginReport.plugin)
    ).all())


def is_fresh(report: ServerPluginReport) -> bool:
    return report.reported_at is not None and utc_now() - report.reported_at <= timedelta(seconds=FRESH_SECONDS)


def modules(session: Session, server: GameServer) -> dict[str, dict[str, Any]]:
    """Every module any fresh report says is working: ``{name: {plugin, version, detail}}``."""
    out: dict[str, dict[str, Any]] = {}
    for r in reports(session, server):
        if not is_fresh(r):
            continue
        for name, state in (r.modules or {}).items():
            if isinstance(state, dict) and state.get("ok"):
                out[name] = {"plugin": r.plugin, "version": r.version, "detail": state.get("detail")}
    return out


def missing_required(session: Session, server: GameServer) -> list[str]:
    """Required modules an external server lacks right now (labels, for a message)."""
    if not getattr(server, "is_external", False):
        return []
    have = modules(session, server)
    return [label for key, label in REQUIRED_MODULES.items() if key not in have]


def monitoring(session: Session, server: GameServer) -> dict[str, Any] | None:
    """Latest fresh numbers of the monitoring module, or None."""
    for r in reports(session, server):
        state = (r.modules or {}).get("monitoring")
        if is_fresh(r) and isinstance(state, dict) and state.get("ok") and r.data:
            return {**r.data, "plugin": r.plugin, "version": r.version, "core": r.core,
                    "reported_at": r.reported_at.isoformat()}
    return None
