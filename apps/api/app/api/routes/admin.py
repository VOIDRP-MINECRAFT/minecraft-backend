from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.schemas.admin import (
    AdminLegacySummaryResponse,
    AdminLegacyUpdateRequest,
    AdminLegacyUpdateResponse,
    AdminPlayerRecord,
    AdminPlayersListResponse,
)
from apps.api.app.services.admin_player_service import AdminPlayerService

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_access)],
)


def get_admin_player_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> AdminPlayerService:
    return AdminPlayerService(session=session)


@router.get("/players/summary", response_model=AdminLegacySummaryResponse)
def get_legacy_summary(
    service: Annotated[AdminPlayerService, Depends(get_admin_player_service)],
) -> AdminLegacySummaryResponse:
    return service.get_summary()


@router.get("/players", response_model=AdminPlayersListResponse)
def list_players(
    q: str | None = Query(default=None, max_length=320),
    legacy_auth_enabled: bool | None = Query(default=None),
    legacy_hash_present: bool | None = Query(default=None),
    user_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    service: Annotated[AdminPlayerService, Depends(get_admin_player_service)] = None,
) -> AdminPlayersListResponse:
    assert service is not None
    return service.list_players(
        q=q,
        legacy_auth_enabled=legacy_auth_enabled,
        legacy_hash_present=legacy_hash_present,
        user_active=user_active,
        limit=limit,
    )


@router.get("/players/{player_account_id}", response_model=AdminPlayerRecord)
def get_player(
    player_account_id: UUID,
    service: Annotated[AdminPlayerService, Depends(get_admin_player_service)],
) -> AdminPlayerRecord:
    record = service.get_player(player_account_id=player_account_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="player account was not found",
        )
    return record


@router.patch("/players/{player_account_id}/legacy", response_model=AdminLegacyUpdateResponse)
def update_legacy(
    player_account_id: UUID,
    payload: AdminLegacyUpdateRequest,
    service: Annotated[AdminPlayerService, Depends(get_admin_player_service)],
) -> AdminLegacyUpdateResponse:
    record = service.update_legacy(player_account_id=player_account_id, payload=payload)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="player account was not found",
        )

    return AdminLegacyUpdateResponse(
        message="Legacy settings have been updated.",
        record=record,
    )