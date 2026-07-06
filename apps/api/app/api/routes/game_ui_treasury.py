"""Treasury game-ui endpoints — view nation treasury from the WebGUI browser."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.nation_stats import NationStatsRead, NationTreasuryTransactionListResponse
from apps.api.app.services.nation_stats_service import NationNotFoundError, NationStatsService

router = APIRouter(prefix="/game-ui/treasury", tags=["game-ui", "treasury"])


def _stats_service(db: Annotated[Session, Depends(get_db_session)]) -> NationStatsService:
    return NationStatsService(db)


class TreasurySummary(BaseModel):
    nation_slug: str
    nation_title: str
    role: str
    stats: NationStatsRead
    transactions: NationTreasuryTransactionListResponse


def _resolve_player_nation(player: PlayerAccount, db: Session) -> tuple[Nation, NationMember]:
    member = db.execute(
        select(NationMember).where(NationMember.user_id == player.user_id)
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игрок не состоит в государстве.")
    nation = db.execute(
        select(Nation).where(Nation.id == member.nation_id)
    ).scalar_one_or_none()
    if nation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Государство не найдено.")
    return nation, member


@router.get("/summary", response_model=TreasurySummary)
def get_treasury_summary(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    svc: Annotated[NationStatsService, Depends(_stats_service)],
) -> TreasurySummary:
    nation, member = _resolve_player_nation(player, db)
    try:
        stats = svc.get_stats_by_slug(nation.slug)
        transactions = svc.list_transactions_for_nation(nation.slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TreasurySummary(
        nation_slug=nation.slug,
        nation_title=nation.title,
        role=member.role,
        stats=stats,
        transactions=transactions,
    )
