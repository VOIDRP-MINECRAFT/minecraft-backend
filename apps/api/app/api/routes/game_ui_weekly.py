"""Weekly challenges: plugin push (game-auth) + game-ui read (webgui token)."""
from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_weekly_challenges import PlayerWeeklyChallenges

router = APIRouter(prefix="/game-ui/weekly", tags=["game-ui", "weekly"])
plugin_router = APIRouter(prefix="/game-sync/weekly-challenges", tags=["weekly"])


class ChallengeItem(BaseModel):
    key: str
    title: str
    goal: int
    progress: int
    reward: int
    done: bool


class WeeklyOut(BaseModel):
    week_id: str | None = None
    challenges: list[ChallengeItem] = []


@router.get("", response_model=WeeklyOut)
def get_weekly(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> WeeklyOut:
    row = db.execute(
        select(PlayerWeeklyChallenges).where(
            PlayerWeeklyChallenges.server_id == server.id,
            PlayerWeeklyChallenges.minecraft_nickname_normalized == player.minecraft_nickname.lower(),
        )
    ).scalar_one_or_none()
    if row is None:
        return WeeklyOut()
    return WeeklyOut(week_id=row.week_id, challenges=row.challenges or [])


class WeeklyPush(BaseModel):
    minecraft_nickname: str = Field(min_length=1, max_length=48)
    week_id: str = Field(min_length=1, max_length=16)
    challenges: list[ChallengeItem]


@plugin_router.post("", status_code=status.HTTP_204_NO_CONTENT)
def push_weekly(
    payload: WeeklyPush,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> None:
    norm = payload.minecraft_nickname.strip().lower()
    data = [c.model_dump() for c in payload.challenges]
    stmt = (
        pg_insert(PlayerWeeklyChallenges)
        .values(
            id=uuid4(),
            server_id=server.id,
            minecraft_nickname=payload.minecraft_nickname.strip(),
            minecraft_nickname_normalized=norm,
            week_id=payload.week_id,
            challenges=data,
        )
        .on_conflict_do_update(
            constraint="uq_weekly_challenges_server_nick",
            set_={"week_id": payload.week_id, "challenges": data},
        )
    )
    db.execute(stmt)
    db.commit()
