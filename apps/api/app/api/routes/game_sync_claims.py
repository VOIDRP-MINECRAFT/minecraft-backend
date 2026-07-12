from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.claim import (
    ClaimActionResponse,
    ClaimCreateRequest,
    ClaimListResponse,
    ClaimTrustRequest,
    ClaimUpgradeRequest,
)
from apps.api.app.services.claim_service import ClaimService

router = APIRouter(
    prefix="/claims",
    tags=["claims-game"],
    dependencies=[Depends(require_game_auth_secret)],
)


def get_claim_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> ClaimService:
    return ClaimService(session, server.id)


@router.get("/list", response_model=ClaimListResponse)
def list_claims(
    service: Annotated[ClaimService, Depends(get_claim_service)],
) -> ClaimListResponse:
    return ClaimListResponse(claims=service.list_game())


@router.post("/create", response_model=ClaimActionResponse)
def create_claim(
    payload: ClaimCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[ClaimService, Depends(get_claim_service)],
) -> ClaimActionResponse:
    result = service.create(payload)
    if result.ok:
        session.commit()
    return result


@router.post("/{claim_id}/upgrade", response_model=ClaimActionResponse)
def upgrade_claim(
    claim_id: UUID,
    payload: ClaimUpgradeRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[ClaimService, Depends(get_claim_service)],
) -> ClaimActionResponse:
    result = service.add_cube(claim_id, payload.cube)
    if result.ok:
        session.commit()
    return result


@router.post("/{claim_id}/fill", response_model=ClaimActionResponse)
def fill_claim(
    claim_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[ClaimService, Depends(get_claim_service)],
) -> ClaimActionResponse:
    result = service.fill(claim_id)
    if result.ok:
        session.commit()
    return result


@router.delete("/{claim_id}", response_model=ClaimActionResponse)
def delete_claim(
    claim_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[ClaimService, Depends(get_claim_service)],
) -> ClaimActionResponse:
    result = service.delete(claim_id)
    if result.ok:
        session.commit()
    return result


@router.post("/{claim_id}/trust", response_model=ClaimActionResponse)
def trust_claim(
    claim_id: UUID,
    payload: ClaimTrustRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[ClaimService, Depends(get_claim_service)],
) -> ClaimActionResponse:
    result = service.trust(claim_id, payload.nick, payload.action)
    if result.ok:
        session.commit()
    return result
