from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.tiktok import (
    TikTokCampaignCreateRequest,
    TikTokCampaignResponse,
    TikTokPendingRewardsResponse,
    TikTokRewardAckRequest,
    TikTokRewardAckResponse,
)
from apps.api.app.services.tiktok_service import TikTokService

router = APIRouter(
    prefix="/game-sync/tiktok",
    tags=["tiktok-game"],
    dependencies=[Depends(require_game_auth_secret)],
)


def get_tiktok_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> TikTokService:
    return TikTokService(session, server.id)


@router.post("/campaign", response_model=TikTokCampaignResponse)
def create_campaign(
    payload: TikTokCampaignCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[TikTokService, Depends(get_tiktok_service)],
) -> TikTokCampaignResponse:
    result = service.create_campaign(payload.video_url, payload.deactivate_previous)
    session.commit()
    return result


@router.get("/pending-rewards", response_model=TikTokPendingRewardsResponse)
def pending_rewards(
    service: Annotated[TikTokService, Depends(get_tiktok_service)],
) -> TikTokPendingRewardsResponse:
    return service.list_pending()


@router.post("/pending-rewards/ack", response_model=TikTokRewardAckResponse)
def ack_rewards(
    payload: TikTokRewardAckRequest,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[TikTokService, Depends(get_tiktok_service)],
) -> TikTokRewardAckResponse:
    count = service.ack(payload.ids)
    session.commit()
    return TikTokRewardAckResponse(acknowledged=count)
