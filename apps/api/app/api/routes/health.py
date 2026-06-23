from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", app=settings.app_name)


@router.get("/server/status")
def public_server_status() -> dict:
    """Public endpoint — checks if the Minecraft server is reachable."""
    s = get_settings()
    host = s.minecraft_server_host
    port = s.minecraft_server_port

    if not host:
        return {"online": False}

    try:
        from mcstatus import JavaServer  # type: ignore[import-untyped]

        server = JavaServer(host, port, timeout=3)
        status = server.status()
        return {
            "online": True,
            "players_online": status.players.online,
            "players_max": status.players.max,
        }
    except Exception:
        return {"online": False}


@router.get("/server/stats")
def public_server_stats(session: Annotated[Session, Depends(get_db_session)]) -> dict:
    """Public endpoint — aggregate server statistics for the landing page."""
    from apps.api.app.models.nation import Nation
    from apps.api.app.models.player_account import PlayerAccount

    total_players = session.scalar(select(func.count()).select_from(PlayerAccount)) or 0
    total_nations = session.scalar(select(func.count()).select_from(Nation)) or 0

    return {
        "total_players": total_players,
        "total_nations": total_nations,
        "mods_count": 320,
    }
