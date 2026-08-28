"""Battle Pass game-ui endpoints — view player progress from the WebGUI browser."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.battlepass import BattlePassPublicProfileResponse
from apps.api.app.services.battlepass_service import BattlePassService
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(prefix="/game-ui/battlepass", tags=["game-ui", "battlepass"])
plugin_router = APIRouter(prefix="/game-sync/battlepass", tags=["battlepass"])

_TRACK_TTL = 172800


def _track_key(server_id, nick: str) -> str:
    return f"bp:track:{server_id}:{nick.lower()}"


class BpReward(BaseModel):
    type: str | None = None          # money | exp | item
    display_name: str | None = None
    amount: float = 0
    material: str | None = None
    count: int = 0


class BpTrackLevel(BaseModel):
    level: int
    free: BpReward | None = None
    premium: BpReward | None = None
    free_claimed: bool = False
    premium_claimed: bool = False


class BpTrack(BaseModel):
    season: str | None = None
    level: int = 0
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


def _service(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BattlePassService:
    return BattlePassService(session=db, server_id=server.id)


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
