"""Player playtime activity: plugin push (game-auth) + in-game chart (webgui token)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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
from apps.api.app.models.player_playtime_daily import PlayerPlaytimeDaily

router = APIRouter(prefix="/game-ui/activity", tags=["game-ui", "activity"])
plugin_router = APIRouter(prefix="/game-sync/playtime", tags=["activity"])


class ActivityDay(BaseModel):
    day: date
    minutes: int


class ActivityOut(BaseModel):
    days: list[ActivityDay]
    total_minutes: int


@router.get("", response_model=ActivityOut)
def get_activity(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    days: int = 14,
) -> ActivityOut:
    span = max(1, min(days, 60))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=span - 1)
    rows = db.execute(
        select(PlayerPlaytimeDaily.day, PlayerPlaytimeDaily.seconds).where(
            PlayerPlaytimeDaily.server_id == server.id,
            PlayerPlaytimeDaily.minecraft_nickname_normalized == player.minecraft_nickname.lower(),
            PlayerPlaytimeDaily.day >= start,
        )
    ).all()
    by_day = {r[0]: int(r[1] or 0) for r in rows}
    # Emit a zero-filled continuous series so the chart has one bar per day.
    out = [
        ActivityDay(day=start + timedelta(days=i), minutes=by_day.get(start + timedelta(days=i), 0) // 60)
        for i in range(span)
    ]
    return ActivityOut(days=out, total_minutes=sum(d.minutes for d in out))


class PlaytimePush(BaseModel):
    minecraft_nickname: str = Field(min_length=1, max_length=48)
    seconds: int = Field(ge=0)
    day: date | None = None  # defaults to server-side today


@plugin_router.post("", status_code=status.HTTP_204_NO_CONTENT)
def push_playtime(
    payload: PlaytimePush,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> None:
    if payload.seconds <= 0:
        return
    norm = payload.minecraft_nickname.strip().lower()
    day = payload.day or datetime.now(timezone.utc).date()
    # Atomic upsert-add so concurrent pushes accumulate rather than clobber.
    stmt = (
        pg_insert(PlayerPlaytimeDaily)
        .values(
            id=uuid4(),
            server_id=server.id,
            minecraft_nickname=payload.minecraft_nickname.strip(),
            minecraft_nickname_normalized=norm,
            day=day,
            seconds=payload.seconds,
        )
        .on_conflict_do_update(
            constraint="uq_playtime_daily_server_nick_day",
            set_={"seconds": PlayerPlaytimeDaily.seconds + payload.seconds},
        )
    )
    db.execute(stmt)
    db.commit()
