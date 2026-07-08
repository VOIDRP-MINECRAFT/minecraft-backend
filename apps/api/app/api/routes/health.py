from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", app=settings.app_name)


@router.get("/server/status")
def public_server_status(
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    """Public endpoint — checks if the selected game server is reachable."""
    from apps.api.app.api.routes.servers import _to_public

    st = _to_public(server).status
    if st is None or not st.online:
        return {"online": False}
    return {
        "online": True,
        "players_online": st.players_online,
        "players_max": st.players_max,
    }


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
