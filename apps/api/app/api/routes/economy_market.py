from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.schemas.economy_market import (
    EconomyMarketPriceListResponse,
    EconomyMarketPriceRead,
    EconomyMarketRecalculateResponse,
    EconomyShopTransactionCreate,
    EconomyShopTransactionRead,
    NationMarketCancelRequest,
    NationMarketCancelResponse,
    NationMarketListingCreate,
    NationMarketListingListResponse,
    NationMarketListingRead,
    NationMarketPurchaseRequest,
    NationMarketPurchaseResponse,
)
from apps.api.app.services.economy_market_service import (
    EconomyMarketConflictError,
    EconomyMarketNotFoundError,
    EconomyMarketService,
    EconomyMarketValidationError,
)

router = APIRouter(prefix="/game-sync", tags=["game-sync", "economy-market"])


def get_economy_market_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> EconomyMarketService:
    return EconomyMarketService(session=session)


@router.get(
    "/economy/prices",
    response_model=EconomyMarketPriceListResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def list_market_prices(
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> EconomyMarketPriceListResponse:
    return service.list_prices()


@router.get(
    "/economy/prices/{material}",
    response_model=EconomyMarketPriceRead,
    dependencies=[Depends(require_game_auth_secret)],
)
def get_market_price(
    material: str,
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> EconomyMarketPriceRead:
    return service.get_price(material)


@router.post(
    "/economy/recalculate",
    response_model=EconomyMarketRecalculateResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def recalculate_market_prices(
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
    decay_scores: bool = Query(default=True),
) -> EconomyMarketRecalculateResponse:
    return service.recalculate_prices(decay_scores=decay_scores)


@router.post(
    "/economy/transactions",
    response_model=EconomyShopTransactionRead,
    dependencies=[Depends(require_game_auth_secret)],
)
def record_shop_transaction(
    payload: EconomyShopTransactionCreate,
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> EconomyShopTransactionRead:
    try:
        return service.record_shop_transaction(payload)
    except EconomyMarketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.post(
    "/nation-market/listings",
    response_model=NationMarketListingRead,
    dependencies=[Depends(require_game_auth_secret)],
)
def create_nation_market_listing(
    payload: NationMarketListingCreate,
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> NationMarketListingRead:
    try:
        return service.create_nation_listing(payload)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except EconomyMarketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.get(
    "/nation-market/listings",
    response_model=NationMarketListingListResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def list_nation_market_listings(
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
    nation_slug: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
) -> NationMarketListingListResponse:
    try:
        return service.list_nation_market_listings(
            nation_slug=nation_slug,
            include_inactive=include_inactive,
            limit=limit,
        )
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.get(
    "/nation-market/listings/{listing_id}",
    response_model=NationMarketListingRead,
    dependencies=[Depends(require_game_auth_secret)],
)
def get_nation_market_listing(
    listing_id: UUID,
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> NationMarketListingRead:
    try:
        return service.get_nation_listing(listing_id)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post(
    "/nation-market/listings/{listing_id}/purchase",
    response_model=NationMarketPurchaseResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def purchase_nation_market_listing(
    listing_id: UUID,
    payload: NationMarketPurchaseRequest,
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> NationMarketPurchaseResponse:
    try:
        return service.purchase_nation_listing(listing_id, payload)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except EconomyMarketConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=translate_user_message(str(exc))) from exc
    except EconomyMarketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.post(
    "/nation-market/listings/{listing_id}/cancel",
    response_model=NationMarketCancelResponse,
    dependencies=[Depends(require_game_auth_secret)],
)
def cancel_nation_market_listing(
    listing_id: UUID,
    payload: NationMarketCancelRequest,
    service: Annotated[EconomyMarketService, Depends(get_economy_market_service)],
) -> NationMarketCancelResponse:
    try:
        return service.cancel_nation_listing(listing_id, payload.requester_player_name)
    except EconomyMarketNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except EconomyMarketConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=translate_user_message(str(exc))) from exc
    except EconomyMarketValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc
