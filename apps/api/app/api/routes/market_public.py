from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.schemas.market_public import (
    PriceHistoryResponse,
    PublicMarketItemListResponse,
    PublicMarketItemRead,
    PublicMarketListingListResponse,
    PublicMarketSummaryResponse,
    PublicMarketTransactionListResponse,
)
from apps.api.app.services.economy_market_service import EconomyMarketNotFoundError
from apps.api.app.services.market_public_service import MarketPublicService

router = APIRouter(prefix="/market", tags=["market"])


def get_market_public_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> MarketPublicService:
    return MarketPublicService(session=session)


@router.get("/summary", response_model=PublicMarketSummaryResponse)
def get_market_summary(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> PublicMarketSummaryResponse:
    return service.get_summary()


@router.get("/items", response_model=PublicMarketItemListResponse)
def list_market_items(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
    q: str | None = Query(default=None, max_length=128),
    group_key: str | None = Query(default=None, max_length=64),
    sort: str = Query(default="material", max_length=32),
    direction: str = Query(default="asc", max_length=8),
    limit: int = Query(default=200, ge=1, le=500),
) -> PublicMarketItemListResponse:
    return service.list_items(q=q, group_key=group_key, sort=sort, direction=direction, limit=limit)


@router.get("/items/{material}", response_model=PublicMarketItemRead)
def get_market_item(
    material: str,
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> PublicMarketItemRead:
    try:
        return service.get_item(material)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.get("/items/{material}/history", response_model=PriceHistoryResponse)
def get_market_item_history(
    material: str,
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
    days: int = Query(default=30, ge=1, le=90),
) -> PriceHistoryResponse:
    try:
        return service.get_price_history(material, days=days)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.get("/nation-listings", response_model=PublicMarketListingListResponse)
def list_nation_market_listings_public(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
    q: str | None = Query(default=None, max_length=128),
    nation_slug: str | None = Query(default=None, max_length=64),
    material: str | None = Query(default=None, max_length=96),
    limit: int = Query(default=100, ge=1, le=200),
) -> PublicMarketListingListResponse:
    return service.list_nation_listings(q=q, nation_slug=nation_slug, material=material, limit=limit)


@router.get("/transactions", response_model=PublicMarketTransactionListResponse)
def list_market_transactions_public(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
    material: str | None = Query(default=None, max_length=96),
    limit: int = Query(default=50, ge=1, le=200),
) -> PublicMarketTransactionListResponse:
    return service.list_transactions(material=material, limit=limit)
