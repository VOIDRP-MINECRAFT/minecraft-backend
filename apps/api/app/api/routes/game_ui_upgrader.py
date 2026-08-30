"""Void Upgrader — WebGUI endpoints (spend Void Coins to gamble toward an item)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.services.void_upgrader_service import (
    MAX_MULTIPLIER,
    MIN_STAKE,
    RTP,
    VoidUpgraderError,
    VoidUpgraderService,
)

router = APIRouter(prefix="/game-ui/upgrader", tags=["game-ui", "upgrader"])


class RewardOut(BaseModel):
    id: str
    item_key: str
    display_name: str
    image_url: str | None
    vc_value: int
    amount: int
    tier: str


class RewardsResponse(BaseModel):
    void_coins: int
    rtp: float
    min_stake: int
    max_multiplier: float
    rewards: list[RewardOut]


class SpinRequest(BaseModel):
    reward_id: UUID
    stake: int = Field(..., ge=1)
    client_seed: str | None = None


class HistoryItem(BaseModel):
    reward_display: str
    reward_item_key: str
    stake: int
    multiplier: float
    win_chance: float
    won: bool
    created_at: str


@router.get("/rewards", response_model=RewardsResponse)
def get_rewards(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> RewardsResponse:
    svc = VoidUpgraderService(db, server.id)
    rewards = svc.rewards()
    return RewardsResponse(
        void_coins=int(player.void_coins or 0),
        rtp=RTP,
        min_stake=MIN_STAKE,
        max_multiplier=MAX_MULTIPLIER,
        rewards=[
            RewardOut(
                id=str(r.id), item_key=r.item_key, display_name=r.display_name,
                image_url=r.image_url, vc_value=int(r.vc_value), amount=int(r.amount or 1), tier=r.tier,
            )
            for r in rewards
        ],
    )


@router.post("/spin")
def spin(
    req: SpinRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    svc = VoidUpgraderService(db, server.id)
    try:
        return svc.spin(player, req.reward_id, req.stake, req.client_seed)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/history", response_model=list[HistoryItem])
def get_history(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[HistoryItem]:
    svc = VoidUpgraderService(db, server.id)
    return [
        HistoryItem(
            reward_display=s.reward_display, reward_item_key=s.reward_item_key, stake=int(s.stake),
            multiplier=round(float(s.multiplier), 2), win_chance=round(float(s.win_chance), 4),
            won=s.won, created_at=s.created_at.isoformat(),
        )
        for s in svc.history(player.user_id)
    ]
