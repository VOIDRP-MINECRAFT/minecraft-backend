from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.killfeed import KillEventIngest, KillEventIngestResponse
from apps.api.app.services.killfeed_service import KillfeedService

router = APIRouter(
    prefix="/game-sync",
    tags=["killfeed-game"],
    dependencies=[Depends(require_game_auth_secret)],
)


@router.post("/kill-event", response_model=KillEventIngestResponse)
def ingest_kill_event(
    payload: KillEventIngest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> KillEventIngestResponse:
    KillfeedService(session, server.id).record(payload)
    session.commit()
    return KillEventIngestResponse(ok=True)
