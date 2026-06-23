from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.schemas.battlepass import (
    AdminBattlePassPlayerInfo,
    BattlePassPremiumGrantRequest,
    BattlePassPremiumListResponse,
    BattlePassPremiumResponse,
)
from apps.api.app.services.battlepass_service import (
    BattlePassNotFoundError,
    BattlePassService,
)

router = APIRouter(
    prefix="/admin/battlepass",
    tags=["admin", "battlepass"],
    dependencies=[Depends(require_admin_access)],
)


def get_battlepass_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> BattlePassService:
    return BattlePassService(session=session)


@router.get("/premium", response_model=BattlePassPremiumListResponse)
def list_premium(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    active_only: bool = Query(default=True),
    service: Annotated[BattlePassService, Depends(get_battlepass_service)] = None,
) -> BattlePassPremiumListResponse:
    assert service is not None
    if active_only:
        return service.list_active_premium(skip=skip, limit=limit)
    return service.list_all_premium(skip=skip, limit=limit)


@router.post("/premium/grant", response_model=BattlePassPremiumResponse)
def admin_grant_premium(
    payload: BattlePassPremiumGrantRequest,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassPremiumResponse:
    return service.grant_premium(payload, granted_by="admin")


@router.delete("/premium/{minecraft_uuid}")
def revoke_premium(
    minecraft_uuid: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> dict[str, bool]:
    try:
        service.revoke_premium(minecraft_uuid)
    except BattlePassNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"ok": True}


@router.post("/premium/revoke-by-nick/{nickname}")
def revoke_premium_by_nick(
    nickname: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> dict[str, bool]:
    """Revoke by nickname: updates DB if record exists, always sends RCON."""
    service.revoke_premium_by_nick(nickname)
    return {"ok": True}


@router.get("/player-by-nick/{nickname}", response_model=AdminBattlePassPlayerInfo)
def get_player_by_nick(
    nickname: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> AdminBattlePassPlayerInfo:
    return service.get_admin_player_info_by_nick(nickname)


@router.get("/stats")
def get_stats(
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> dict[str, int]:
    return service.get_stats()
