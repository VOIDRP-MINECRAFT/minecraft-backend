from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.schemas.play_ticket import (
    ConsumeByIpRequest,
    ConsumePlayTicketRequest,
    ConsumePlayTicketResponse,
    IssuePlayTicketRequest,
    IssuePlayTicketResponse,
)
from apps.api.app.core.audit import client_ip
from apps.api.app.core.permissions import may_join_during_maintenance
from apps.api.app.services.consent_service import ConsentService
from apps.api.app.services.play_ticket_service import PlayTicketService, PlayTicketValidationError

launcher_router = APIRouter(prefix="/launcher", tags=["launcher"])
server_router = APIRouter(prefix="/server/auth", tags=["server-auth"])


def get_play_ticket_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> PlayTicketService:
    return PlayTicketService(session=session, server_id=server.id)


def get_game_ticket_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> PlayTicketService:
    """For the game server's own calls: the server is the one its secret belongs to — a
    partner server's plugin must not depend on sending the right X-Server-Slug."""
    return PlayTicketService(session=session, server_id=server.id)


@launcher_router.post("/play-ticket", response_model=IssuePlayTicketResponse)
def issue_play_ticket(
    payload: IssuePlayTicketRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayTicketService, Depends(get_play_ticket_service)],
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> IssuePlayTicketResponse:
    # Maintenance closes the server for everyone but platform admins and holders of
    # servers.maintenance.join on it. The launcher greys out «Играть» too, but only this
    # check really keeps people out. 409 so the launcher shows the text as it is.
    if server.maintenance and not may_join_during_maintenance(current_user, server):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"На сервере «{server.name}» идут технические работы. Зайти можно будет, когда они закончатся.",
        )
    # The game is entered only after the offer and the personal data consent are accepted. The
    # launcher asks for them right after login; older launchers get this message instead. 409 (not
    # 403) so the launcher shows it without treating it as an expired session.
    if ConsentService(session).status(current_user.id)["missing"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Мы обновили правила проекта. Подтвердите договор оферты и согласие на обработку персональных данных в лаунчере или на сайте void-rp.ru, чтобы продолжить играть.",
        )
    try:
        issued = service.issue_for_user(
            user=current_user,
            launcher_version=payload.launcher_version,
            launcher_platform=payload.launcher_platform,
            issued_ip=client_ip(request),
        )
    except PlayTicketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=translate_user_message(str(exc))) from exc

    return IssuePlayTicketResponse(
        ticket=issued.ticket,
        expires_at=issued.expires_at,
        minecraft_nickname=issued.minecraft_nickname,
        ttl_seconds=issued.ttl_seconds,
        hostname_label=issued.hostname_label,
    )


@server_router.post(
    "/consume-play-ticket",
    response_model=ConsumePlayTicketResponse,
)
def consume_play_ticket(
    payload: ConsumePlayTicketRequest,
    service: Annotated[PlayTicketService, Depends(get_game_ticket_service)],
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


@server_router.post(
    "/consume-by-ip",
    response_model=ConsumePlayTicketResponse,
)
def consume_play_ticket_by_ip(
    payload: ConsumeByIpRequest,
    service: Annotated[PlayTicketService, Depends(get_game_ticket_service)],
) -> ConsumePlayTicketResponse:
    """Lets a player in at join by the ticket their launcher took from the same IP, without
    waiting for the client to send it. 400 = nothing matches; the server then waits for the
    client's ticket as before."""
    try:
        consumed = service.consume_by_ip(player_name=payload.player_name, ip=payload.ip)
    except PlayTicketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=translate_user_message(str(exc))) from exc

    return ConsumePlayTicketResponse(
        user_id=consumed.user_id,
        minecraft_nickname=consumed.minecraft_nickname,
        legacy_auth_enabled=consumed.legacy_auth_enabled,
        expires_at=consumed.expires_at,
    )
