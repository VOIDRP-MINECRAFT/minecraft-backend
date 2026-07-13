from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.killfeed import KillfeedResponse
from apps.api.app.services.killfeed_service import KillfeedService

router = APIRouter(prefix="/killfeed", tags=["killfeed"])


@router.get("", response_model=KillfeedResponse)
def killfeed(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> KillfeedResponse:
    """Recent PvP kills for the active server — who killed whom, never coordinates,
    so it is safe to show publicly on an anarchy server."""
    return KillfeedService(session, server.id).recent()
