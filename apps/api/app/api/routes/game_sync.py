from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.schemas.game_sync import (
    GameNationListResponse,
    GameNationMembershipSyncRequest,
    GameNationMembershipSyncResponse,
    GameNationSummaryResponse,
    GameReferralRewardResolveResponse,
    NationCapitalUpdateRequest,
)
from apps.api.app.services.game_sync_service import GameSyncService, GameSyncValidationError
from apps.api.app.services.nation_service import NationNotFoundError

router = APIRouter(prefix="/game-sync", tags=["game-sync"])


def get_game_sync_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> GameSyncService:
    return GameSyncService(session=session)


@router.get(
    "/nations",
    response_model=GameNationListResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def list_game_sync_nations(
    service: Annotated[GameSyncService, Depends(get_game_sync_service)],
) -> GameNationListResponse:
    return service.list_nations_for_game_sync()


@router.get(
    "/nations/{slug}/summary",
    response_model=GameNationSummaryResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def get_game_nation_summary(
    slug: str,
    service: Annotated[GameSyncService, Depends(get_game_sync_service)],
) -> GameNationSummaryResponse:
    try:
        return service.get_nation_summary(slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post(
    "/nations/{slug}/membership",
    response_model=GameNationMembershipSyncResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def sync_game_nation_membership(
    slug: str,
    payload: GameNationMembershipSyncRequest,
    service: Annotated[GameSyncService, Depends(get_game_sync_service)],
) -> GameNationMembershipSyncResponse:
    try:
        return service.sync_nation_membership(slug, payload)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except GameSyncValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.post(
    "/nations/{slug}/capital",
    dependencies=[Depends(require_game_auth_secret)],
    status_code=204,
)
def set_nation_capital(
    slug: str,
    payload: NationCapitalUpdateRequest,
    service: Annotated[GameSyncService, Depends(get_game_sync_service)],
) -> None:
    try:
        service.set_nation_capital(slug, payload)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.get(
    "/referrals/reward/{minecraft_nickname}",
    response_model=GameReferralRewardResolveResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def resolve_game_referral_reward(
    minecraft_nickname: str,
    service: Annotated[GameSyncService, Depends(get_game_sync_service)],
) -> GameReferralRewardResolveResponse:
    try:
        return service.resolve_active_referral_reward(minecraft_nickname)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc
