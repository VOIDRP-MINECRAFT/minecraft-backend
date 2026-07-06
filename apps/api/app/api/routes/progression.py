from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.progression import (
    FullLeaderboardRead,
    PlayerProgressionRead,
    TierUnlockRequest,
    TierUnlockResponse,
)
from apps.api.app.services.progression_service import ProgressionService, UnknownTierError

router = APIRouter(prefix="/progression", tags=["progression"])


def get_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> ProgressionService:
    return ProgressionService(session, server.id)


@router.post("/internal/unlock", response_model=TierUnlockResponse)
def unlock_tier(
    payload: TierUnlockRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[ProgressionService, Depends(get_service)],
) -> TierUnlockResponse:
    try:
        return service.unlock_tier(payload)
    except UnknownTierError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/player/{minecraft_nickname}", response_model=PlayerProgressionRead | None)
def get_player_progression(
    minecraft_nickname: str,
    service: Annotated[ProgressionService, Depends(get_service)],
) -> PlayerProgressionRead | None:
    return service.get_player_progression(minecraft_nickname)


@router.get("/leaderboard", response_model=FullLeaderboardRead)
def get_leaderboard(
    service: Annotated[ProgressionService, Depends(get_service)],
) -> FullLeaderboardRead:
    return service.get_leaderboard()
