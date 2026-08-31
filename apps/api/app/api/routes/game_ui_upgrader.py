"""Void Upgrader — WebGUI endpoints (spend Void Coins to gamble toward an item)."""
from __future__ import annotations

import hashlib
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
    VoidUpgraderError,
    VoidUpgraderService,
)

router = APIRouter(prefix="/game-ui/upgrader", tags=["game-ui", "upgrader"])


def _require_feature(server: GameServer) -> None:
    """The upgrader is a per-server feature (game_servers.features['upgrader']).
    Absent/unknown key ⇒ enabled (matches the rest of the features contract)."""
    features = getattr(server, "features", None) or {}
    if features.get("upgrader") is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Апгрейдер отключён на этом сервере.")


class RewardOut(BaseModel):
    id: str
    item_key: str
    display_name: str
    image_url: str | None
    vc_value: int
    amount: int
    tier: str


class JackpotOut(BaseModel):
    enabled: bool
    amount: int
    last_winner: str | None = None
    last_amount: int | None = None


class DailyOut(BaseModel):
    enabled: bool
    available: bool
    free_stake: int
    streak: int
    bp_level: int = 0


class FairnessOut(BaseModel):
    commit_hash: str
    nonce: int
    rotated_at: str | None = None


class RewardsResponse(BaseModel):
    void_coins: int
    rtp: float
    min_stake: int
    max_multiplier: float
    max_chance: float
    rewards: list[RewardOut]
    jackpot: JackpotOut
    daily: DailyOut
    fairness: FairnessOut


class SpinRequest(BaseModel):
    reward_id: UUID
    stake: int = Field(..., ge=1)
    client_seed: str | None = None


class DailySpinRequest(BaseModel):
    reward_id: UUID
    client_seed: str | None = None


class LeaderboardEntry(BaseModel):
    nickname: str
    biggest_win: int
    total_won: int
    wins: int
    prestige: int = 0


class LeaderboardOut(BaseModel):
    week_start: str
    entries: list[LeaderboardEntry]


class HistoryItem(BaseModel):
    reward_display: str
    reward_item_key: str
    stake: int
    multiplier: float
    win_chance: float
    won: bool
    created_at: str
    # provably-fair — server_seed_hash is the commit (always); server_seed is revealed only
    # once the player rotates the seed it belongs to.
    server_seed: str | None = None
    server_seed_hash: str | None = None
    client_seed: str | None = None
    nonce: int | None = None
    roll: float | None = None


class StatsOut(BaseModel):
    spins: int
    wins: int
    win_rate: float
    vc_staked: int
    vc_won: int


class RecentWin(BaseModel):
    nickname: str
    reward_display: str
    reward_item_key: str
    stake: int
    multiplier: float
    created_at: str
    prestige: int = 0


@router.get("/rewards", response_model=RewardsResponse)
def get_rewards(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> RewardsResponse:
    _require_feature(server)
    svc = VoidUpgraderService(db, server.id)
    rewards = svc.rewards()
    cfg = svc.settings()
    return RewardsResponse(
        void_coins=int(player.void_coins or 0),
        rtp=cfg["rtp"],
        min_stake=cfg["min_stake"],
        max_multiplier=cfg["max_multiplier"],
        max_chance=cfg["max_chance"],
        rewards=[
            RewardOut(
                id=str(r.id), item_key=r.item_key, display_name=r.display_name,
                image_url=r.image_url, vc_value=int(r.vc_value), amount=int(r.amount or 1), tier=r.tier,
            )
            for r in rewards
        ],
        jackpot=JackpotOut(**svc.jackpot()),
        daily=DailyOut(**svc.daily_status(player)),
        fairness=FairnessOut(**svc.fairness(player)),
    )


@router.post("/spin")
def spin(
    req: SpinRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    _require_feature(server)
    svc = VoidUpgraderService(db, server.id)
    try:
        return svc.spin(player, req.reward_id, req.stake, req.client_seed)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/daily-spin")
def daily_spin(
    req: DailySpinRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    _require_feature(server)
    svc = VoidUpgraderService(db, server.id)
    try:
        return svc.spin(player, req.reward_id, 0, req.client_seed, free=True)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/jackpot", response_model=JackpotOut)
def get_jackpot(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> JackpotOut:
    _require_feature(server)
    return JackpotOut(**VoidUpgraderService(db, server.id).jackpot())


@router.get("/leaderboard", response_model=LeaderboardOut)
def get_leaderboard(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> LeaderboardOut:
    _require_feature(server)
    return LeaderboardOut(**VoidUpgraderService(db, server.id).weekly_leaderboard())


class WinningOut(BaseModel):
    id: str
    item_key: str
    display_name: str
    vc_value: int
    amount: int
    tier: str


@router.get("/winnings", response_model=list[WinningOut])
def get_winnings(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[WinningOut]:
    svc = VoidUpgraderService(db, server.id)
    return [
        WinningOut(id=str(w.id), item_key=w.item_key, display_name=w.display_name,
                   vc_value=int(w.vc_value), amount=int(w.amount or 1), tier=w.tier)
        for w in svc.winnings(player.user_id)
    ]


@router.post("/winnings/{winning_id}/claim")
def claim_winning(
    winning_id: UUID,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    try:
        return VoidUpgraderService(db, server.id).claim(player, winning_id)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/winnings/{winning_id}/sell")
def sell_winning(
    winning_id: UUID,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    try:
        return VoidUpgraderService(db, server.id).sell(player, winning_id)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class UpgradeWinningRequest(BaseModel):
    target_reward_id: UUID
    client_seed: str | None = None


@router.post("/winnings/{winning_id}/upgrade")
def upgrade_winning(
    winning_id: UUID,
    req: UpgradeWinningRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    _require_feature(server)
    try:
        return VoidUpgraderService(db, server.id).upgrade_winning(
            player, winning_id, req.target_reward_id, req.client_seed
        )
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/winnings/sell-all")
def sell_all_winnings(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    try:
        return VoidUpgraderService(db, server.id).sell_all(player)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/winnings/claim-all")
def claim_all_winnings(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    try:
        return VoidUpgraderService(db, server.id).claim_all(player)
    except VoidUpgraderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/stats", response_model=StatsOut)
def get_stats(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> StatsOut:
    svc = VoidUpgraderService(db, server.id)
    return StatsOut(**svc.stats(player.user_id))


@router.get("/recent-wins", response_model=list[RecentWin])
def recent_wins(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[RecentWin]:
    _require_feature(server)
    svc = VoidUpgraderService(db, server.id)
    wins = svc.recent_wins()
    pres = svc.prestige_map([s.minecraft_nickname for s in wins])
    return [
        RecentWin(
            nickname=s.minecraft_nickname, reward_display=s.reward_display,
            reward_item_key=s.reward_item_key, stake=int(s.stake),
            multiplier=round(float(s.multiplier), 2), created_at=s.created_at.isoformat(),
            prestige=pres.get(s.minecraft_nickname.lower(), 0),
        )
        for s in wins
    ]


@router.get("/history", response_model=list[HistoryItem])
def get_history(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[HistoryItem]:
    svc = VoidUpgraderService(db, server.id)
    active_seed = svc.active_seed_value(player)   # spins under the STILL-active seed stay committed-only
    return [
        HistoryItem(
            reward_display=s.reward_display, reward_item_key=s.reward_item_key, stake=int(s.stake),
            multiplier=round(float(s.multiplier), 2), win_chance=round(float(s.win_chance), 4),
            won=s.won, created_at=s.created_at.isoformat(),
            server_seed=(None if s.server_seed == active_seed else s.server_seed),
            server_seed_hash=hashlib.sha256(s.server_seed.encode()).hexdigest() if s.server_seed else None,
            client_seed=s.client_seed, nonce=s.nonce,
            roll=round(float(s.roll), 6) if s.roll is not None else None,
        )
        for s in svc.history(player.user_id)
    ]


class RotateOut(BaseModel):
    revealed_seed: str
    revealed_hash: str
    revealed_spins: int
    commit_hash: str


@router.get("/fairness", response_model=FairnessOut)
def get_fairness(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> FairnessOut:
    return FairnessOut(**VoidUpgraderService(db, server.id).fairness(player))


@router.post("/fairness/rotate", response_model=RotateOut)
def rotate_fairness(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> RotateOut:
    return RotateOut(**VoidUpgraderService(db, server.id).rotate_seed(player))
