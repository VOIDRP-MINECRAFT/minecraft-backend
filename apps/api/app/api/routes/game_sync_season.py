"""Season (top-nation reward) endpoints — plugin-facing (game-auth secret)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.services.nation_season_service import NationSeasonService

plugin_router = APIRouter(prefix="/game-sync/season", tags=["season"])


@plugin_router.post("/award-top")
def award_top_nations(
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Pay the weekly top nations (idempotent per period). Driven by the gamesync plugin."""
    return NationSeasonService(db, server.id).award_weekly_top_nations()
