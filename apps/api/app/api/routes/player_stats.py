from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.schemas.player_stats import PlayerTopResponse
from apps.api.app.services.player_stats_service import PlayerStatsService

router = APIRouter(prefix="/players", tags=["players"])


def get_service(session: Annotated[Session, Depends(get_db_session)]) -> PlayerStatsService:
    return PlayerStatsService(session)


@router.get("/top", response_model=PlayerTopResponse)
def get_players_top(
    service: Annotated[PlayerStatsService, Depends(get_service)],
) -> PlayerTopResponse:
    return service.get_top()
