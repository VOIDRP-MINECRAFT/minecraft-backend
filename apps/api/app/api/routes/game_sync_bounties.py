from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.bounty import (
    BountyActionResponse,
    BountyBoardResponse,
    BountyClaimRequest,
    BountyPlaceRequest,
)
from apps.api.app.services.bounty_service import BountyService

router = APIRouter(
    prefix="/bounties",
    tags=["bounties-game"],
    dependencies=[Depends(require_game_auth_secret)],
)


def get_bounty_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> BountyService:
    return BountyService(session, server.id)


@router.post("/place", response_model=BountyActionResponse)
def place_bounty(
    payload: BountyPlaceRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[BountyService, Depends(get_bounty_service)],
) -> BountyActionResponse:
    result = service.place(payload)
    if result.ok:
        session.commit()
    return result


@router.post("/claim", response_model=BountyActionResponse)
def claim_bounty(
    payload: BountyClaimRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[BountyService, Depends(get_bounty_service)],
) -> BountyActionResponse:
    result = service.claim(payload)
    if result.ok:
        session.commit()
    return result


@router.get("/board", response_model=BountyBoardResponse)
def bounty_board_game(
    service: Annotated[BountyService, Depends(get_bounty_service)],
) -> BountyBoardResponse:
    return service.board()
