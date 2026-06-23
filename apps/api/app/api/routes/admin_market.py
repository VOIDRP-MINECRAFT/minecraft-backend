from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.schemas.market_public import (
    AdminMarketActionResponse,
    AdminMarketItemPatch,
    AdminMarketRecalculateResponse,
    PublicMarketItemListResponse,
    PublicMarketSummaryResponse,
)
from apps.api.app.services.economy_market_service import EconomyMarketNotFoundError
from apps.api.app.services.market_public_service import MarketPublicService

router = APIRouter(
    prefix="/admin/market",
    tags=["admin", "market"],
    dependencies=[Depends(require_admin_access)],
)


def get_market_public_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> MarketPublicService:
    return MarketPublicService(session=session)


@router.get("/summary", response_model=PublicMarketSummaryResponse)
def get_admin_market_summary(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> PublicMarketSummaryResponse:
    return service.get_summary()


@router.get("/items", response_model=PublicMarketItemListResponse)
def list_admin_market_items(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
    q: str | None = Query(default=None, max_length=128),
    include_disabled: bool = Query(default=True),
    sort: str = Query(default="updated", max_length=32),
    direction: str = Query(default="desc", max_length=8),
    limit: int = Query(default=300, ge=1, le=500),
) -> PublicMarketItemListResponse:
    return service.list_items(q=q, include_disabled=include_disabled, sort=sort, direction=direction, limit=limit)


@router.patch("/items/{material}", response_model=AdminMarketActionResponse)
def patch_admin_market_item(
    material: str,
    payload: AdminMarketItemPatch,
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> AdminMarketActionResponse:
    try:
        return service.patch_item(material, payload)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post("/items/{material}/enable", response_model=AdminMarketActionResponse)
def enable_admin_market_item(
    material: str,
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> AdminMarketActionResponse:
    try:
        return service.enable_item(material, True)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post("/items/{material}/disable", response_model=AdminMarketActionResponse)
def disable_admin_market_item(
    material: str,
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> AdminMarketActionResponse:
    try:
        return service.enable_item(material, False)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post("/items/{material}/reset", response_model=AdminMarketActionResponse)
def reset_admin_market_item(
    material: str,
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
) -> AdminMarketActionResponse:
    try:
        return service.reset_item(material)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post("/recalculate", response_model=AdminMarketRecalculateResponse)
def recalculate_admin_market(
    service: Annotated[MarketPublicService, Depends(get_market_public_service)],
    decay_scores: bool = Query(default=True),
) -> AdminMarketRecalculateResponse:
    return service.recalculate(decay_scores=decay_scores)
