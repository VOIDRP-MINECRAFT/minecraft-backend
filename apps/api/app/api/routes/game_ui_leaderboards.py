"""Leaderboards for the in-game WebGUI (nations + players)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_stat_cache import PlayerStatCache

router = APIRouter(prefix="/game-ui/leaderboards", tags=["game-ui", "leaderboards"])

_TOP = 10


class LbEntry(BaseModel):
    rank: int
    name: str
    tag: str | None = None
    accent: str | None = None
    value: float


class Leaderboards(BaseModel):
    nations: dict[str, list[LbEntry]]
    players: dict[str, list[LbEntry]]


@router.get("", response_model=Leaderboards)
def get_leaderboards(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> Leaderboards:
    def nations(attr: str) -> list[LbEntry]:
        col = getattr(NationStat, attr)
        rows = db.execute(
            select(NationStat, Nation)
            .join(Nation, Nation.id == NationStat.nation_id)
            .where(NationStat.server_id == server.id, col > 0, Nation.is_technical.is_(False))
            .order_by(col.desc())
            .limit(_TOP)
        ).all()
        return [
            LbEntry(rank=i + 1, name=nat.title, tag=nat.tag, accent=nat.accent_color, value=float(getattr(st, attr)))
            for i, (st, nat) in enumerate(rows)
        ]

    def players(attr: str) -> list[LbEntry]:
        col = getattr(PlayerStatCache, attr)
        rows = db.execute(
            select(PlayerStatCache)
            .where(PlayerStatCache.server_id == server.id, col > 0)
            .order_by(col.desc())
            .limit(_TOP)
        ).scalars().all()
        return [
            LbEntry(rank=i + 1, name=s.minecraft_nickname, value=float(getattr(s, attr)))
            for i, s in enumerate(rows)
        ]

    return Leaderboards(
        nations={
            "prestige": nations("prestige_score"),
            "treasury": nations("treasury_balance"),
            "territory": nations("territory_points"),
            "pvp": nations("pvp_kills"),
        },
        players={
            "pvp": players("pvp_kills"),
            "playtime": players("total_playtime_minutes"),
            "balance": players("current_balance"),
            "quests": players("completed_quests"),
        },
    )
