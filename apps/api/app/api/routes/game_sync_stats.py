from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.game_stats import PlayerStatsBatchRequest, PlayerStatsBatchResponse
from apps.api.app.services.player_stat_ingest_service import PlayerStatIngestService

router = APIRouter(
    prefix="/game-sync",
    tags=["game-sync-stats"],
    dependencies=[Depends(require_game_auth_secret)],
)


@router.post("/player-stats", response_model=PlayerStatsBatchResponse)
def ingest_player_stats(
    payload: PlayerStatsBatchRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> PlayerStatsBatchResponse:
    service = PlayerStatIngestService(session, server.id)
    updated = service.apply_batch(payload)
    session.commit()
    return PlayerStatsBatchResponse(ok=True, updated=updated)
