from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.models.game_server import GameServer
from apps.api.app.repositories.game_server_repository import GameServerRepository
from apps.api.app.schemas.game_server import GameServerPublic, GameServerStatus

router = APIRouter(prefix="/servers", tags=["servers"])

# Lightweight per-process TTL cache for status pings (avoid hammering servers).
_STATUS_TTL_SECONDS = 30
_status_cache: dict[str, tuple[float, GameServerStatus]] = {}


def _ping_status(host: str, port: int) -> GameServerStatus:
    cache_key = f"{host}:{port}"
    now = time.monotonic()
    cached = _status_cache.get(cache_key)
    if cached and (now - cached[0]) < _STATUS_TTL_SECONDS:
        return cached[1]

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

    _status_cache[cache_key] = (now, result)
    return result


def _to_public(server: GameServer, with_status: bool = True) -> GameServerPublic:
    dto = GameServerPublic.model_validate(server)
    if with_status:
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
        host = host or server.host
        port = port or server.port
        dto.status = _ping_status(host, port)
    return dto


@router.get("", response_model=list[GameServerPublic])
def list_servers(session: Annotated[Session, Depends(get_db_session)]) -> list[GameServerPublic]:
    servers = GameServerRepository(session).list_visible()
    return [_to_public(s) for s in servers]


@router.get("/{slug}", response_model=GameServerPublic)
def get_server(
    slug: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameServerPublic:
    server = GameServerRepository(session).get_by_slug(slug)
    if server is None or not server.is_visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return _to_public(server)
