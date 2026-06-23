"""Game-UI market endpoints — accessed directly from the WebGUI browser via webgui_token."""
from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import PlayerMarketWebAction
from apps.api.app.schemas.player_market import (
    PlayerMarketItemSummaryListResponse,
    PlayerMarketOrderBookResponse,
    PlayerMarketSellOrderListResponse,
    PlayerMarketBuyOrderListResponse,
    PlayerMarketSellOrderPublicRead,
    PlayerMarketBuyOrderRead,
    PlayerMarketTradeListResponse,
)
from apps.api.app.services.player_market_service import PlayerMarketService

router = APIRouter(prefix="/game-ui/market", tags=["game-ui", "player-market"])


def _service(db: Annotated[Session, Depends(get_db_session)]) -> PlayerMarketService:
    return PlayerMarketService(db)


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("/items", response_model=PlayerMarketItemSummaryListResponse)
def get_items(svc: Annotated[PlayerMarketService, Depends(_service)]):
    return svc.list_items_summary()


@router.get("/order-book/{item_key:path}", response_model=PlayerMarketOrderBookResponse)
def get_order_book(item_key: str, svc: Annotated[PlayerMarketService, Depends(_service)]):
    return svc.get_order_book(item_key)


@router.get("/my-sell-orders", response_model=PlayerMarketSellOrderListResponse)
def get_my_sell_orders(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[PlayerMarketService, Depends(_service)],
):
    orders = svc.list_my_sell_orders(player.minecraft_nickname)
    return PlayerMarketSellOrderListResponse(
        items=[PlayerMarketSellOrderPublicRead.model_validate(o) for o in orders]
    )


@router.get("/my-buy-orders", response_model=PlayerMarketBuyOrderListResponse)
def get_my_buy_orders(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[PlayerMarketService, Depends(_service)],
):
    orders = svc.list_my_buy_orders(player.minecraft_nickname)
    return PlayerMarketBuyOrderListResponse(
        items=[PlayerMarketBuyOrderRead.model_validate(o) for o in orders]
    )


@router.get("/my-trades", response_model=PlayerMarketTradeListResponse)
def get_my_trades(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[PlayerMarketService, Depends(_service)],
):
    return svc.list_my_trades(player.minecraft_nickname)


class PendingDeliveriesResponse(BaseModel):
    count: int


@router.get("/pickup-ready", response_model=PendingDeliveriesResponse)
def get_pickup_ready(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[PlayerMarketService, Depends(_service)],
):
    result = svc.get_pending_deliveries(player.minecraft_nickname)
    return PendingDeliveriesResponse(count=len(result.deliveries))


# ---------------------------------------------------------------------------
# Pending web actions (buy / cancel — need Vault, processed by plugin)
# ---------------------------------------------------------------------------

class WebActionRequest(BaseModel):
    action_type: str  # buy | cancel_buy | cancel_sell | pickup
    payload: dict[str, Any] = {}


class WebActionResponse(BaseModel):
    action_id: str
    status: str


@router.post("/pending-action", response_model=WebActionResponse, status_code=status.HTTP_201_CREATED)
def create_pending_action(
    req: WebActionRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
):
    allowed = {"buy", "cancel_buy", "cancel_sell", "pickup"}
    if req.action_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown action_type: {req.action_type}")

    action = PlayerMarketWebAction(
        player_name=player.minecraft_nickname,
        action_type=req.action_type,
        payload_json=req.payload,
        status="pending",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return WebActionResponse(action_id=str(action.id), status=action.status)


# ---------------------------------------------------------------------------
# Plugin endpoint: poll + ack pending actions (game-auth, not webgui_token)
# ---------------------------------------------------------------------------

class WebActionPluginItem(BaseModel):
    action_id: str
    player_name: str
    action_type: str
    payload: dict[str, Any]


class WebActionPluginListResponse(BaseModel):
    actions: list[WebActionPluginItem]


class WebActionAckRequest(BaseModel):
    action_id: str
    status: str  # done | failed
    error_message: str | None = None


from apps.api.app.dependencies.server_auth import require_game_auth_secret  # noqa: E402

router_plugin = APIRouter(prefix="/game-sync/market-web-actions", tags=["game-sync", "player-market"])


@router_plugin.get("", response_model=WebActionPluginListResponse)
def poll_pending_actions(
    player_name: str | None = None,
    db: Session = Depends(get_db_session),
    _: None = Depends(require_game_auth_secret),
):
    q = db.query(PlayerMarketWebAction).filter(PlayerMarketWebAction.status == "pending")
    if player_name:
        q = q.filter(PlayerMarketWebAction.player_name == player_name)
    actions = q.order_by(PlayerMarketWebAction.created_at).limit(50).all()
    return WebActionPluginListResponse(
        actions=[
            WebActionPluginItem(
                action_id=str(a.id),
                player_name=a.player_name,
                action_type=a.action_type,
                payload=a.payload_json,
            )
            for a in actions
        ]
    )


@router_plugin.post("/ack")
def ack_action(
    req: WebActionAckRequest,
    db: Session = Depends(get_db_session),
    _: None = Depends(require_game_auth_secret),
):
    from datetime import datetime, timezone
    action = db.query(PlayerMarketWebAction).filter(
        PlayerMarketWebAction.id == UUID(req.action_id)
    ).first()
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    action.status = req.status
    action.error_message = req.error_message
    action.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
