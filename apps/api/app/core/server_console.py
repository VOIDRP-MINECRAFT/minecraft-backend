"""Console and log of a server through our plugin instead of RCON and local files.

A partner's server (docs/external_servers_plan.md) runs VoidRpPerms 0.5.0+, which reports the
``console`` and ``log`` modules. Then every command the backend would send over RCON goes to
``server_commands`` instead: the plugin takes it within a couple of seconds, runs it on the
server and posts the output back — so the partner can close RCON. The log tail the plugin
ships lands in ``server_log_lines`` and feeds the admin's log and chat.
"""
from __future__ import annotations

import time
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from apps.api.app.core import server_reports
from apps.api.app.core.security import utc_now
from apps.api.app.db import SessionLocal
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_console import ServerCommand, ServerLogLine

LOG_KEEP_LINES = 5000
# A command nobody took by then is dropped — the plugin must not run a stale kick later.
PENDING_TTL_SECONDS = 60

_route_cache: dict = {}
_ROUTE_CACHE_SECONDS = 5.0


class PluginConsoleError(OSError):
    """The plugin did not run the command (no answer in time, or it failed)."""


def has_module(session: Session, server: GameServer, key: str) -> bool:
    return key in server_reports.modules(session, server)


def uses_plugin_log(session: Session, server: GameServer) -> bool:
    """The admin's log/chat come from the plugin: a partner's server, or one whose log file we
    cannot reach. Our own servers keep reading their full log file straight off disk."""
    from apps.api.app.core import server_ops

    if not has_module(session, server, "log"):
        return False
    return bool(getattr(server, "is_external", False)) or not server_ops.resolve_log_path(server)


def routes_through_plugin(server: GameServer) -> bool:
    """Commands for this server go to its plugin: it reports the console module, and the
    server is a partner's (RCON over the internet) or has no RCON at all."""
    rcon = bool(server.rcon_port and server.rcon_password is not None)
    if not getattr(server, "is_external", False) and rcon:
        return False
    now = time.monotonic()
    hit = _route_cache.get(server.id)
    if hit and now - hit[0] < _ROUTE_CACHE_SECONDS:
        return hit[1]
    with SessionLocal() as session:
        fresh = session.get(GameServer, server.id)
        ok = fresh is not None and has_module(session, fresh, "console")
    _route_cache[server.id] = (now, ok)
    return ok


def run(server: GameServer, command: str, timeout: float = 8.0) -> str:
    """Queues ``command`` for the server's plugin and waits for its output."""
    with SessionLocal() as session:
        row = ServerCommand(server_id=server.id, command=command, status="pending")
        session.add(row)
        session.commit()
        cmd_id = row.id
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        time.sleep(0.3)
        with SessionLocal() as session:
            row = session.get(ServerCommand, cmd_id)
            if row is not None and row.status in ("done", "failed"):
                if row.status == "failed":
                    raise PluginConsoleError(row.output or "команда не выполнена")
                return row.output or ""
    with SessionLocal() as session:
        # Still not taken: drop it so it does not run later out of the blue.
        session.execute(update(ServerCommand).where(ServerCommand.id == cmd_id, ServerCommand.status == "pending")
                        .values(status="expired", done_at=utc_now()))
        session.commit()
        row = session.get(ServerCommand, cmd_id)
        if row is not None and row.status == "sent":
            return "(команда отправлена на сервер, ответ не пришёл вовремя)"
    raise PluginConsoleError("сервер не забрал команду: плагин VoidRpPerms не отвечает")


def take_pending(session: Session, server: GameServer, limit: int = 20) -> list[ServerCommand]:
    """Commands for the plugin to run now; marked sent so they run once."""
    now = utc_now()
    session.execute(update(ServerCommand).where(
        ServerCommand.server_id == server.id, ServerCommand.status == "pending",
        ServerCommand.created_at < now - timedelta(seconds=PENDING_TTL_SECONDS)).values(status="expired", done_at=now))
    rows = list(session.scalars(select(ServerCommand).where(
        ServerCommand.server_id == server.id, ServerCommand.status == "pending")
        .order_by(ServerCommand.id).limit(limit).with_for_update(skip_locked=True)).all())
    for r in rows:
        r.status = "sent"
    session.commit()
    return rows


def append_log(session: Session, server: GameServer, lines: list[str]) -> int:
    if not lines:
        return 0
    session.add_all([ServerLogLine(server_id=server.id, line=ln[:4000]) for ln in lines[-2000:]])
    session.flush()
    top = session.scalar(select(func.max(ServerLogLine.id)).where(ServerLogLine.server_id == server.id)) or 0
    session.execute(delete(ServerLogLine).where(ServerLogLine.server_id == server.id,
                                                ServerLogLine.id <= top - LOG_KEEP_LINES))
    session.commit()
    return len(lines)


def tail(session: Session, server: GameServer, lines: int) -> list[str]:
    rows = session.scalars(select(ServerLogLine.line).where(ServerLogLine.server_id == server.id)
                           .order_by(ServerLogLine.id.desc()).limit(lines)).all()
    return list(reversed(rows))
