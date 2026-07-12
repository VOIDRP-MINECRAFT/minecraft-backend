from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.schemas.claim import ClaimSiteListResponse
from apps.api.app.services.claim_service import ClaimService

router = APIRouter(prefix="/account/claims", tags=["claims"])


@router.get("", response_model=ClaimSiteListResponse)
def list_my_claims(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ClaimSiteListResponse:
    service = ClaimService(session, server.id)
    return ClaimSiteListResponse(claims=service.list_site_for_user(current_user.id))
