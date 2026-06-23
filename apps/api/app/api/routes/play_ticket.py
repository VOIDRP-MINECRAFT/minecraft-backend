from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.models.user import User
from apps.api.app.schemas.play_ticket import (
    ConsumePlayTicketRequest,
    ConsumePlayTicketResponse,
    IssuePlayTicketRequest,
    IssuePlayTicketResponse,
)
from apps.api.app.services.play_ticket_service import PlayTicketService, PlayTicketValidationError

launcher_router = APIRouter(prefix="/launcher", tags=["launcher"])
server_router = APIRouter(prefix="/server/auth", tags=["server-auth"])


def get_play_ticket_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> PlayTicketService:
    return PlayTicketService(session=session)


@launcher_router.post("/play-ticket", response_model=IssuePlayTicketResponse)
def issue_play_ticket(
    payload: IssuePlayTicketRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayTicketService, Depends(get_play_ticket_service)],
) -> IssuePlayTicketResponse:
    try:
        issued = service.issue_for_user(
            user=current_user,
            launcher_version=payload.launcher_version,
            launcher_platform=payload.launcher_platform,
        )
    except PlayTicketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=translate_user_message(str(exc))) from exc

    return IssuePlayTicketResponse(
        ticket=issued.ticket,
        expires_at=issued.expires_at,
        minecraft_nickname=issued.minecraft_nickname,
        ttl_seconds=issued.ttl_seconds,
    )


@server_router.post(
    "/consume-play-ticket",
    response_model=ConsumePlayTicketResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def consume_play_ticket(
    payload: ConsumePlayTicketRequest,
    service: Annotated[PlayTicketService, Depends(get_play_ticket_service)],
) -> ConsumePlayTicketResponse:
    try:
        consumed = service.consume(
            raw_ticket=payload.ticket,
            player_name=payload.player_name,
            launcher_proof=payload.launcher_proof,
        )
    except PlayTicketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=translate_user_message(str(exc))) from exc

    return ConsumePlayTicketResponse(
        user_id=consumed.user_id,
        minecraft_nickname=consumed.minecraft_nickname,
        legacy_auth_enabled=consumed.legacy_auth_enabled,
        expires_at=consumed.expires_at,
    )
