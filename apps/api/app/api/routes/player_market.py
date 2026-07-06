from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.schemas.player_market import (
    PlayerMarketBuyOrderCreate,
    PlayerMarketBuyOrderListResponse,
    PlayerMarketBuyOrderRead,
    PlayerMarketCancelBuyOrderResponse,
    PlayerMarketCancelOrderRequest,
    PlayerMarketCancelSellOrderResponse,
    PlayerMarketCreateBuyOrderResponse,
    PlayerMarketCreateSellOrderResponse,
    PlayerMarketDeliveryAckRequest,
    PlayerMarketExpireResponse,
    PlayerMarketItemSummaryListResponse,
    PlayerMarketOrderBookResponse,
    PlayerMarketPendingDeliveriesResponse,
    PlayerMarketSellOrderCreate,
    PlayerMarketSellOrderListResponse,
    PlayerMarketSellOrderPublicRead,
    PlayerMarketTradeListResponse,
)
from apps.api.app.services.player_market_service import (
    PlayerMarketConflictError,
    PlayerMarketNotFoundError,
    PlayerMarketService,
    PlayerMarketValidationError,
)

# ── Router A: game-sync (plugin calls, require X-Game-Auth-Secret) ─────────────
router_game_sync = APIRouter(prefix="/game-sync/player-market", tags=["game-sync", "player-market"])

# ── Router B: public read (frontend, no auth) ─────────────────────────────────
router_public = APIRouter(prefix="/market/player", tags=["player-market"])

# ── Router C: authenticated player routes (frontend "My Orders") ──────────────
router_player = APIRouter(prefix="/market/player/me", tags=["player-market"])


def get_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> PlayerMarketService:
    return PlayerMarketService(session, server.id)


# ── Game-sync endpoints ────────────────────────────────────────────────────────

@router_game_sync.post("/sell-orders", response_model=PlayerMarketCreateSellOrderResponse)
def game_create_sell_order(
    payload: PlayerMarketSellOrderCreate,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketCreateSellOrderResponse:
    try:
        return service.create_sell_order(payload)
    except PlayerMarketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router_game_sync.post("/buy-orders", response_model=PlayerMarketCreateBuyOrderResponse)
def game_create_buy_order(
    payload: PlayerMarketBuyOrderCreate,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketCreateBuyOrderResponse:
    try:
        return service.create_buy_order(payload)
    except PlayerMarketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router_game_sync.post("/sell-orders/{order_id}/cancel", response_model=PlayerMarketCancelSellOrderResponse)
def game_cancel_sell_order(
    order_id: UUID,
    payload: PlayerMarketCancelOrderRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketCancelSellOrderResponse:
    try:
        return service.cancel_sell_order(order_id, payload.requester_player_name)
    except PlayerMarketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PlayerMarketConflictError, PlayerMarketValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router_game_sync.post("/buy-orders/{order_id}/cancel", response_model=PlayerMarketCancelBuyOrderResponse)
def game_cancel_buy_order(
    order_id: UUID,
    payload: PlayerMarketCancelOrderRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketCancelBuyOrderResponse:
    try:
        return service.cancel_buy_order(order_id, payload.requester_player_name)
    except PlayerMarketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PlayerMarketConflictError, PlayerMarketValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router_game_sync.get(
    "/pending-deliveries/{player_name}",
    response_model=PlayerMarketPendingDeliveriesResponse,
)
def game_get_pending_deliveries(
    player_name: str,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketPendingDeliveriesResponse:
    return service.get_pending_deliveries(player_name)


@router_game_sync.post(
    "/pending-deliveries/{player_name}/ack",
    response_model=dict,
)
def game_ack_pending_deliveries(
    player_name: str,
    payload: PlayerMarketDeliveryAckRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> dict:
    acked = service.ack_deliveries(player_name, payload)
    return {"acked": acked}


@router_game_sync.post("/expire", response_model=PlayerMarketExpireResponse)
def game_expire_orders(
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketExpireResponse:
    return service.expire_orders()


# ── Public endpoints ───────────────────────────────────────────────────────────

@router_public.get("/items", response_model=PlayerMarketItemSummaryListResponse)
def public_list_items(
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketItemSummaryListResponse:
    return service.list_items_summary()


@router_public.get("/order-book/{item_key:path}", response_model=PlayerMarketOrderBookResponse)
def public_get_order_book(
    item_key: str,
    service: Annotated[PlayerMarketService, Depends(get_service)],
) -> PlayerMarketOrderBookResponse:
    return service.get_order_book(item_key)


@router_public.get("/sell-orders", response_model=PlayerMarketSellOrderListResponse)
def public_list_sell_orders(
    service: Annotated[PlayerMarketService, Depends(get_service)],
    item_key: str | None = Query(default=None, max_length=192),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlayerMarketSellOrderListResponse:
    orders = service.list_sell_orders(item_key=item_key, limit=limit)
    return PlayerMarketSellOrderListResponse(
        total=len(orders),
        items=[PlayerMarketSellOrderPublicRead.model_validate(o) for o in orders],
    )


@router_public.get("/buy-orders", response_model=PlayerMarketBuyOrderListResponse)
def public_list_buy_orders(
    service: Annotated[PlayerMarketService, Depends(get_service)],
    item_key: str | None = Query(default=None, max_length=192),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlayerMarketBuyOrderListResponse:
    orders = service.list_buy_orders(item_key=item_key, limit=limit)
    return PlayerMarketBuyOrderListResponse(
        total=len(orders),
        items=[PlayerMarketBuyOrderRead.model_validate(o) for o in orders],
    )


@router_public.get("/trades", response_model=PlayerMarketTradeListResponse)
def public_list_trades(
    service: Annotated[PlayerMarketService, Depends(get_service)],
    item_key: str | None = Query(default=None, max_length=192),
    limit: int = Query(default=50, ge=1, le=200),
) -> PlayerMarketTradeListResponse:
    return service.list_trades(item_key=item_key, limit=limit)


# ── Auth-protected player endpoints ───────────────────────────────────────────

@router_player.get("/sell-orders")
def me_list_sell_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> PlayerMarketSellOrderListResponse:
    nick = _get_nick(current_user)
    if not nick:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Никнейм не привязан.")
    orders = service.list_my_sell_orders(nick, include_inactive=include_inactive, limit=limit)
    return PlayerMarketSellOrderListResponse(
        total=len(orders),
        items=[PlayerMarketSellOrderPublicRead.model_validate(o) for o in orders],
    )


@router_player.get("/buy-orders")
def me_list_buy_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> PlayerMarketBuyOrderListResponse:
    nick = _get_nick(current_user)
    if not nick:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Никнейм не привязан.")
    orders = service.list_my_buy_orders(nick, include_inactive=include_inactive, limit=limit)
    return PlayerMarketBuyOrderListResponse(
        total=len(orders),
        items=[PlayerMarketBuyOrderRead.model_validate(o) for o in orders],
    )


@router_player.get("/trades")
def me_list_trades(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayerMarketService, Depends(get_service)],
    limit: int = Query(default=50, ge=1, le=200),
) -> PlayerMarketTradeListResponse:
    nick = _get_nick(current_user)
    if not nick:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Никнейм не привязан.")
    return service.list_my_trades(nick, limit=limit)


def _get_nick(user: User) -> str | None:
    account = getattr(user, "player_account", None)
    if account is None:
        return None
    return getattr(account, "minecraft_nickname", None)
