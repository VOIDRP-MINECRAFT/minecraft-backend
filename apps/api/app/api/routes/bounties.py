from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.bounty import BountyBoardResponse
from apps.api.app.services.bounty_service import BountyService

router = APIRouter(prefix="/bounties", tags=["bounties"])


@router.get("", response_model=BountyBoardResponse)
def bounty_board(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BountyBoardResponse:
    """Public bounty board for the active server. Shows who has a price on their
    head — not base locations — so it is safe to display on an anarchy server."""
    return BountyService(session, server.id).board()
