from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import can_view_staff_only_servers, maintenance_join_check
from apps.api.app.models.game_server import GameServer
from apps.api.app.repositories.game_server_repository import GameServerRepository
from apps.api.app.schemas.game_server import GameServerPublic, GameServerStatus

router = APIRouter(prefix="/servers", tags=["servers"])

# Per-process status cache. A stale entry is served at once while a background thread
# refreshes it, so a site request never waits on a ping (an offline server costs the full
# timeout); only the very first ping of an address blocks, and those run in parallel.
_STATUS_TTL_SECONDS = 30
_status_cache: dict[str, tuple[float, GameServerStatus]] = {}
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()
_pinger = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mc-status")


def _do_ping(host: str, port: int) -> GameServerStatus:
    result = GameServerStatus(online=False)
    try:
        from mcstatus import JavaServer  # type: ignore[import-untyped]

        srv = JavaServer(host, port, timeout=3)
        st = srv.status()
        result = GameServerStatus(
            online=True,
            players_online=st.players.online,
            players_max=st.players.max,
            version=st.version.name,
        )
    except Exception:
        result = GameServerStatus(online=False)
    _status_cache[f"{host}:{port}"] = (time.monotonic(), result)
    return result


def _refresh(host: str, port: int) -> None:
    key = f"{host}:{port}"
    try:
        _do_ping(host, port)
    finally:
        with _refresh_lock:
            _refreshing.discard(key)


def _ping_status(host: str, port: int) -> GameServerStatus:
    cache_key = f"{host}:{port}"
    cached = _status_cache.get(cache_key)
    if cached is None:
        return _do_ping(host, port)
    if (time.monotonic() - cached[0]) >= _STATUS_TTL_SECONDS:
        with _refresh_lock:
            start = cache_key not in _refreshing
            _refreshing.add(cache_key)
        if start:
            _pinger.submit(_refresh, host, port)
    return cached[1]


def _warm(servers: list[GameServer]) -> None:
    """First-ever pings of several servers at once instead of one after another."""
    cold = {status_address(s) for s in servers}
    cold = [a for a in cold if f"{a[0]}:{a[1]}" not in _status_cache]
    if len(cold) > 1:
        list(_pinger.map(lambda a: _do_ping(*a), cold))


def _to_public(server: GameServer, with_status: bool = True, may_join=None) -> GameServerPublic:
    dto = GameServerPublic.model_validate(server)
    dto.can_join_maintenance = bool(server.maintenance and may_join is not None and may_join(server))
    if with_status:
        dto.status = _ping_status(*status_address(server))
    return dto


def status_address(server: GameServer) -> tuple[str, int]:
    """Where to ping a server for its status (also used by the admin dashboard)."""
    host = server.status_host
    port = server.status_port
    # For the default server, if no explicit status host is set, ping the
    # configured internal MC address rather than the public domain — the
    # backend runs on the same box and pinging the public domain fails
    # (no NAT hairpin), which would wrongly report the server as offline.
    if not host and server.is_default:
        settings = get_settings()
        host = settings.minecraft_server_host or server.host
        port = port or settings.minecraft_server_port or server.port
    return host or server.host, port or server.port


@router.get("", response_model=list[GameServerPublic])
def list_servers(
    session: Annotated[Session, Depends(get_db_session)],
    may_see_hidden: Annotated[object, Depends(can_view_staff_only_servers)],
    may_join: Annotated[object, Depends(maintenance_join_check)],
) -> list[GameServerPublic]:
    servers = [s for s in GameServerRepository(session).list_visible() if not s.staff_only or may_see_hidden(s)]
    _warm(servers)
    return [_to_public(s, may_join=may_join) for s in servers]


@router.get("/{slug}", response_model=GameServerPublic)
def get_server(
    slug: str,
    session: Annotated[Session, Depends(get_db_session)],
    may_see_hidden: Annotated[object, Depends(can_view_staff_only_servers)],
    may_join: Annotated[object, Depends(maintenance_join_check)],
) -> GameServerPublic:
    server = GameServerRepository(session).get_by_slug(slug)
    if server is None or not server.is_visible or (server.staff_only and not may_see_hidden(server)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return _to_public(server, may_join=may_join)
