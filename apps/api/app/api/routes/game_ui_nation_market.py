"""Nation Market game-ui endpoints — read listings from the WebGUI browser."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.market_public import (
    PublicMarketListingListResponse,
    PublicMarketListingRead,
)
from apps.api.app.services.market_public_service import MarketPublicService

router = APIRouter(prefix="/game-ui/nation-market", tags=["game-ui", "nation-market"])


def _service(db: Annotated[Session, Depends(get_db_session)]) -> MarketPublicService:
    return MarketPublicService(db)


@router.get("/listings", response_model=PublicMarketListingListResponse)
def list_nation_market_listings(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[MarketPublicService, Depends(_service)],
    q: str | None = Query(default=None, max_length=128),
    nation_slug: str | None = Query(default=None, max_length=64),
    material: str | None = Query(default=None, max_length=96),
    limit: int = Query(default=100, ge=1, le=200),
) -> PublicMarketListingListResponse:
    return svc.list_nation_listings(q=q, nation_slug=nation_slug, material=material, limit=limit)
