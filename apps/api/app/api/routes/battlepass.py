from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.battlepass import (
    BattlePassLeaderboardResponse,
    BattlePassPremiumGrantRequest,
    BattlePassPremiumResponse,
    BattlePassPremiumStatusResponse,
    BattlePassProgressUpsertRequest,
    BattlePassPublicProfileResponse,
)
from apps.api.app.services.battlepass_service import BattlePassService

router = APIRouter(prefix="/battlepass", tags=["battlepass"])


def get_battlepass_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BattlePassService:
    return BattlePassService(session=session, server_id=server.id)


@router.get(
    "/premium/{minecraft_uuid}",
    response_model=BattlePassPremiumStatusResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def get_premium_status(
    minecraft_uuid: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassPremiumStatusResponse:
    return service.get_premium_status(minecraft_uuid)


@router.post(
    "/premium/grant",
    response_model=BattlePassPremiumResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def grant_premium(
    payload: BattlePassPremiumGrantRequest,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassPremiumResponse:
    return service.grant_premium(payload, granted_by="game_server")


@router.post(
    "/progress",
    status_code=204,
    dependencies=[Depends(require_game_auth_secret)],
)
def upsert_progress(
    payload: BattlePassProgressUpsertRequest,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> None:
    service.upsert_progress(payload)


@router.get("/profile/{minecraft_uuid}", response_model=BattlePassPublicProfileResponse)
def get_public_profile(
    minecraft_uuid: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassPublicProfileResponse:
    return service.get_public_profile(minecraft_uuid)


@router.get("/profile-by-nick/{nickname}", response_model=BattlePassPublicProfileResponse | None)
def get_public_profile_by_nick(
    nickname: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassPublicProfileResponse | None:
    return service.get_public_profile_by_nick(nickname)


@router.get("/leaderboard", response_model=BattlePassLeaderboardResponse)
def get_leaderboard(
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassLeaderboardResponse:
    return service.get_leaderboard()
