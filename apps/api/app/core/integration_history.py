"""The «Интеграция» page's history: what happened to a server's VoidRP plugins.

Written from the heartbeat (a module turned on or off, a plugin changed version or appeared)
and from ``integration_watch`` (a required module went quiet and came back), and on secret
rotation. The newest ``KEEP`` events per server are kept.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.models.game_server import GameServer
from apps.api.app.models.integration_event import IntegrationEvent

KEEP = 300

LABELS = {
    "module_on": "включился модуль", "module_off": "выключился модуль", "version": "новая версия",
    "plugin_new": "появился плагин", "quiet": "замолчал", "back": "снова на связи", "secret": "секрет",
}


def add(session: Session, server: GameServer, kind: str, plugin: str | None = None, detail: str | None = None) -> None:
    session.add(IntegrationEvent(server_id=server.id, kind=kind, plugin=plugin, detail=(detail or "")[:300] or None))


def on_heartbeat(session: Session, server: GameServer, plugin: str, old_version: str | None, new_version: str | None,
                 old_modules: dict[str, Any] | None, new_modules: dict[str, Any], first: bool) -> None:
    """Compares a report with the previous one and records what changed. Commits nothing."""
    if first:
        add(session, server, "plugin_new", plugin, f"версия {new_version or '?'}")
        return
    if (old_version or "") != (new_version or ""):
        add(session, server, "version", plugin, f"{old_version or '?'} → {new_version or '?'}")
    old_modules = old_modules or {}
    for name, state in new_modules.items():
        was = _effective_ok(old_modules.get(name))
        now = _effective_ok(state)
        if was != now:
            detail = name if now else f"{name}: {(state or {}).get('detail') or 'без пояснения'}"
            add(session, server, "module_on" if now else "module_off", plugin, detail)


# States a module passes through on every start or on a single missed poll: not worth a line.
_TRANSIENT = ("ещё не получен", "нет связи с админкой")


def _effective_ok(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    return bool(state.get("ok")) or any(t in (state.get("detail") or "") for t in _TRANSIENT)


def trim(session: Session, server: GameServer) -> None:
    ids = session.scalars(select(IntegrationEvent.id).where(IntegrationEvent.server_id == server.id)
                          .order_by(IntegrationEvent.id.desc()).offset(KEEP)).all()
    if ids:
        session.execute(delete(IntegrationEvent).where(IntegrationEvent.id.in_(ids)))


def recent(session: Session, server: GameServer, limit: int = 60) -> list[dict[str, Any]]:
    rows = session.scalars(select(IntegrationEvent).where(IntegrationEvent.server_id == server.id)
                           .order_by(IntegrationEvent.id.desc()).limit(limit)).all()
    return [{"at": r.at.isoformat(), "kind": r.kind, "label": LABELS.get(r.kind, r.kind),
             "plugin": r.plugin, "detail": r.detail} for r in rows]
