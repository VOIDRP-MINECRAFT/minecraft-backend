"""HUD snapshot endpoint — accessed from the WebGUI browser overlay."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import PlayerMarketPendingDelivery
from apps.api.app.models.player_stat_cache import PlayerStatCache

router = APIRouter(prefix="/game-ui/hud", tags=["game-ui", "hud"])


class HudSnapshot(BaseModel):
    balance: float
    nation_name: str | None
    nation_role: str | None
    pending_deliveries: int
    completed_quests: int


@router.get("/snapshot", response_model=HudSnapshot)
def get_hud_snapshot(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> HudSnapshot:
    nickname_norm = player.minecraft_nickname.strip().lower()

    stat = db.execute(
        select(PlayerStatCache).where(
            PlayerStatCache.minecraft_nickname_normalized == nickname_norm
        )
    ).scalar_one_or_none()

    balance: float = float(stat.current_balance) if stat else 0.0
    completed_quests: int = int(stat.completed_quests) if stat else 0

    member = db.execute(
        select(NationMember).where(NationMember.user_id == player.user_id)
    ).scalar_one_or_none()

    nation_name: str | None = None
    nation_role: str | None = None
    if member is not None:
        nation_role = member.role
        nation = db.execute(
            select(Nation).where(Nation.id == member.nation_id)
        ).scalar_one_or_none()
        if nation is not None:
            nation_name = nation.title

    pending_deliveries: int = db.execute(
        select(func.count(PlayerMarketPendingDelivery.id)).where(
            PlayerMarketPendingDelivery.player_name == player.minecraft_nickname,
            PlayerMarketPendingDelivery.delivered == False,  # noqa: E712
        )
    ).scalar_one()

    return HudSnapshot(
        balance=balance,
        nation_name=nation_name,
        nation_role=nation_role,
        pending_deliveries=int(pending_deliveries),
        completed_quests=completed_quests,
    )
