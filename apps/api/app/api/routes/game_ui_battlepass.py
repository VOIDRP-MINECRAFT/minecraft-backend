"""Battle Pass game-ui endpoints — view player progress from the WebGUI browser."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.battlepass import BattlePassProgress
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.battlepass import BattlePassPremiumGrantRequest, BattlePassPublicProfileResponse
from apps.api.app.services.battlepass_service import BattlePassService
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(prefix="/game-ui/battlepass", tags=["game-ui", "battlepass"])
plugin_router = APIRouter(prefix="/game-sync/battlepass", tags=["battlepass"])

_TRACK_TTL = 172800
PREMIUM_VC_PRICE = 2000            # Void Coins to unlock premium
PREMIUM_VC_DAYS = 30               # a purchase grants a flat 30 days


def _track_key(server_id, nick: str) -> str:
    return f"bp:track:{server_id}:{nick.lower()}"


class BpReward(BaseModel):
    type: str | None = None          # money | exp | item | command | voidcoin
    display_name: str | None = None
    amount: float = 0
    material: str | None = None
    count: int = 0
    icon: str | None = None          # item id for the WebGUI texture


class BpTrackLevel(BaseModel):
    level: int
    free: BpReward | None = None
    premium: BpReward | None = None
    free_claimed: bool = False
    premium_claimed: bool = False


class BpTrack(BaseModel):
    season: str | None = None
    level: int = 0
    prestige: int = 0
    xp: int = 0
    xp_per_level: int = 10000
    has_premium: bool = False
    ends_in_days: int | None = None
    levels: list[BpTrackLevel] = []


class BpTrackPush(BpTrack):
    minecraft_nickname: str


@plugin_router.post("/track")
def push_track(
    payload: BpTrackPush,
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    cache = RedisCacheService()
    data = BpTrack(**{k: v for k, v in payload.model_dump().items() if k != "minecraft_nickname"}).model_dump()
    cache.set_json(_track_key(server.id, payload.minecraft_nickname), data, ttl_seconds=_TRACK_TTL)
    return {"ok": True}


@router.get("/track", response_model=BpTrack)
def get_track(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BpTrack:
    data = RedisCacheService().get_json(_track_key(server.id, player.minecraft_nickname))
    if not data:
        return BpTrack()
    return BpTrack(**data)


# ── daily quests (mirror of the track: plugin pushes, WebGUI reads) ──
def _quests_key(server_id, nick: str) -> str:
    return f"bp:quests:{server_id}:{nick.lower()}"


class BpQuest(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    type: str | None = None
    progress: int = 0
    required: int = 1
    xp: int = 0
    completed: bool = False


class BpQuests(BaseModel):
    date: str | None = None
    has_premium: bool = False
    free: list[BpQuest] = []
    premium: list[BpQuest] = []


class BpQuestsPush(BpQuests):
    minecraft_nickname: str


@plugin_router.post("/quests")
def push_quests(
    payload: BpQuestsPush,
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    cache = RedisCacheService()
    data = BpQuests(**{k: v for k, v in payload.model_dump().items() if k != "minecraft_nickname"}).model_dump()
    cache.set_json(_quests_key(server.id, payload.minecraft_nickname), data, ttl_seconds=_TRACK_TTL)
    return {"ok": True}


@router.get("/quests", response_model=BpQuests)
def get_quests(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BpQuests:
    data = RedisCacheService().get_json(_quests_key(server.id, player.minecraft_nickname))
    if not data:
        return BpQuests()
    return BpQuests(**data)


# ── plugin fetches the active season config (dates / level cap / name) ──
class BpSeasonResponse(BaseModel):
    season_key: str
    name: str
    start_date: str
    end_date: str
    max_level: int


@plugin_router.get("/season", response_model=BpSeasonResponse)
def get_active_season_for_plugin(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> BpSeasonResponse:
    """The plugin fetches its active season so dates/level-cap/name are backend-managed.
    404 → the plugin keeps its config.yml values."""
    from apps.api.app.models.battlepass_season import BattlePassSeason

    s = db.execute(
        select(BattlePassSeason).where(
            BattlePassSeason.server_id == server.id,
            BattlePassSeason.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="no active season")
    return BpSeasonResponse(
        season_key=s.season_key, name=s.name,
        start_date=s.start_date.isoformat(), end_date=s.end_date.isoformat(),
        max_level=s.max_level,
    )


# ── plugin fetches its reward definitions (admin-edited, per season) ──
class BpRewardDef(BaseModel):
    type: str
    displayName: str | None = None
    command: str | None = None
    material: str | None = None
    count: int | None = None
    amount: float | None = None
    icon: str | None = None


class BpRewardsResponse(BaseModel):
    season: str
    free: dict[int, BpRewardDef] = {}
    premium: dict[int, BpRewardDef] = {}


@plugin_router.get("/rewards", response_model=BpRewardsResponse)
def get_rewards_for_plugin(
    season: str,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> BpRewardsResponse:
    """The battle-pass plugin fetches the admin-edited reward table for a season.

    Returns rewards.yml-compatible entries so SeasonRewards can parse them directly,
    falling back to its bundled rewards.yml if this endpoint is unreachable.
    """
    from apps.api.app.models.battlepass_reward import BattlePassReward

    rows = db.execute(
        select(BattlePassReward).where(
            BattlePassReward.server_id == server.id,
            BattlePassReward.season == season,
        )
    ).scalars().all()

    out = BpRewardsResponse(season=season)
    for r in rows:
        d = BpRewardDef(
            type=r.reward_type.upper(),
            displayName=r.display_name,
            command=r.command,
            material=r.material,
            count=r.count,
            amount=(float(r.amount) if r.amount is not None else None),
            icon=r.icon,
        )
        (out.free if r.track == "free" else out.premium)[r.level] = d
    return out


def _service(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BattlePassService:
    return BattlePassService(session=db, server_id=server.id)


class BuyPremiumResponse(BaseModel):
    ok: bool = True
    price: int
    days: int
    new_void_coins: int
    expires_at: str


@router.post("/buy-premium", response_model=BuyPremiumResponse)
def buy_premium(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BuyPremiumResponse:
    """Unlock Battle Pass premium for the current season by spending Void Coins."""
    # Resolve the player's minecraft UUID (premium is keyed by uuid) from their BP progress.
    prog = db.execute(
        select(BattlePassProgress).where(
            BattlePassProgress.server_id == server.id,
            func.lower(BattlePassProgress.minecraft_nickname) == player.minecraft_nickname.lower(),
        )
    ).scalar_one_or_none()
    if prog is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала зайди в игру, чтобы Battle Pass инициализировался.",
        )

    days = PREMIUM_VC_DAYS   # flat 30 days per purchase (stacks/extends on repeat buys)

    # Atomic conditional decrement — no double-spend if two tabs click at once.
    row = db.execute(
        update(PlayerAccount)
        .where(PlayerAccount.user_id == player.user_id, PlayerAccount.void_coins >= PREMIUM_VC_PRICE)
        .values(void_coins=PlayerAccount.void_coins - PREMIUM_VC_PRICE)
        .returning(PlayerAccount.void_coins)
    ).first()
    if row is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недостаточно Void Coin — нужно {PREMIUM_VC_PRICE}.",
        )
    new_balance = int(row[0])

    # grant_premium commits the session, persisting the VC deduction together with the grant.
    grant = BattlePassService(session=db, server_id=server.id).grant_premium(
        BattlePassPremiumGrantRequest(
            minecraft_uuid=prog.minecraft_uuid,
            minecraft_nickname=player.minecraft_nickname,
            days=days,
            note="Куплено за Void Coin",
        ),
        granted_by="void_coin_shop",
    )
    return BuyPremiumResponse(
        price=PREMIUM_VC_PRICE, days=days, new_void_coins=new_balance,
        expires_at=grant.expires_at.isoformat(),
    )


@router.get("/status", response_model=BattlePassPublicProfileResponse)
def get_battlepass_status(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[BattlePassService, Depends(_service)],
) -> BattlePassPublicProfileResponse:
    profile = svc.get_public_profile_by_nick(player.minecraft_nickname)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Прогресс Battle Pass не найден. Зайди в игру, чтобы инициализировать данные.",
        )
    return profile
