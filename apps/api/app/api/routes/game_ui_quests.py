"""Daily-quest WebGUI view.

The DailyQuests plugin stores quest state locally; it pushes a per-player snapshot
here (Redis, ~2-day TTL — daily data), and the WebGUI reads it back. Claiming is
done via the market "command" web action (`dailyquest claim <index>`).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(prefix="/game-ui/quests", tags=["game-ui", "quests"])
plugin_router = APIRouter(prefix="/game-sync/quests", tags=["quests"])

_SNAPSHOT_TTL = 172800  # 2 days


def _key(server_id, nick: str) -> str:
    return f"quests:daily:{server_id}:{nick.lower()}"


class QuestItem(BaseModel):
    index: int = 0
    template_id: str | None = None
    display_name: str
    description: str | None = None
    type: str | None = None
    target: str | None = None
    required: int = 0
    progress: int = 0
    money_reward: float = 0
    exp_reward: int = 0
    claimed: bool = False


class QuestSnapshot(BaseModel):
    daily: list[QuestItem] = []
    completed_total: int = 0
    reset_date: str | None = None


class QuestSnapshotPush(QuestSnapshot):
    minecraft_nickname: str


@plugin_router.post("/snapshot")
def push_snapshot(
    payload: QuestSnapshotPush,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cache = RedisCacheService()
    data = QuestSnapshot(
        daily=payload.daily, completed_total=payload.completed_total, reset_date=payload.reset_date
    ).model_dump()
    cache.set_json(_key(server.id, payload.minecraft_nickname), data, ttl_seconds=_SNAPSHOT_TTL)
    return {"ok": True}


@router.get("/mine", response_model=QuestSnapshot)
def get_my_quests(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> QuestSnapshot:
    cache = RedisCacheService()
    data = cache.get_json(_key(server.id, player.minecraft_nickname))
    if not data:
        return QuestSnapshot()
    return QuestSnapshot(**data)
