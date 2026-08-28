"""Nation research (tech tree) endpoints.

- ``/game-ui/research/*`` — WebGUI browser (webgui token auth): view + purchase.
- ``/nation-research/effects`` — plugin-facing (game-auth secret): resolved
  per-nation effect map for the gamesync plugin to apply in-world.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.nation_research import (
    NationResearchEffectsResponse,
    NationResearchOverview,
    ResearchPurchaseRequest,
    ResearchPurchaseResponse,
)
from apps.api.app.services.nation_research_service import (
    NationResearchError,
    NationResearchPermissionError,
    NationResearchService,
)

router = APIRouter(prefix="/game-ui/research", tags=["game-ui", "nation-research"])
plugin_router = APIRouter(prefix="/game-sync/nation-research", tags=["nation-research"])


class PluginResearchPurchaseRequest(BaseModel):
    minecraft_nickname: str
    research_key: str


def _service(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NationResearchService:
    return NationResearchService(db, server.id)


def _resolve_player_nation(player: PlayerAccount, db: Session) -> tuple[Nation, NationMember]:
    member = db.execute(
        select(NationMember).where(NationMember.user_id == player.user_id)
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Игрок не состоит в государстве."
        )
    nation = db.execute(
        select(Nation).where(Nation.id == member.nation_id)
    ).scalar_one_or_none()
    if nation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Государство не найдено."
        )
    return nation, member


@router.get("/overview", response_model=NationResearchOverview)
def get_research_overview(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    svc: Annotated[NationResearchService, Depends(_service)],
) -> NationResearchOverview:
    nation, member = _resolve_player_nation(player, db)
    return svc.build_overview(nation, member.role)


@router.post("/purchase", response_model=ResearchPurchaseResponse)
def purchase_research(
    payload: ResearchPurchaseRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    svc: Annotated[NationResearchService, Depends(_service)],
) -> ResearchPurchaseResponse:
    nation, member = _resolve_player_nation(player, db)
    try:
        return svc.purchase(
            nation=nation,
            actor_user_id=player.user_id,
            actor_role=member.role,
            research_key=payload.research_key,
        )
    except NationResearchPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except NationResearchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _resolve_nation_by_nick(
    minecraft_nickname: str, server_id, db: Session
) -> tuple[Nation, NationMember]:
    account = db.execute(
        select(PlayerAccount).where(
            PlayerAccount.minecraft_nickname_normalized == minecraft_nickname.lower()
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игрок не найден.")
    member = db.execute(
        select(NationMember).where(
            NationMember.user_id == account.user_id,
            NationMember.server_id == server_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Игрок не состоит в государстве."
        )
    nation = db.execute(
        select(Nation).where(Nation.id == member.nation_id)
    ).scalar_one_or_none()
    if nation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Государство не найдено."
        )
    return nation, member


@plugin_router.get("/overview", response_model=NationResearchOverview)
def plugin_research_overview(
    minecraft_nickname: str,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> NationResearchOverview:
    nation, member = _resolve_nation_by_nick(minecraft_nickname, server.id, db)
    return NationResearchService(db, server.id).build_overview(nation, member.role)


@plugin_router.post("/purchase", response_model=ResearchPurchaseResponse)
def plugin_purchase_research(
    payload: PluginResearchPurchaseRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ResearchPurchaseResponse:
    nation, member = _resolve_nation_by_nick(payload.minecraft_nickname, server.id, db)
    svc = NationResearchService(db, server.id)
    try:
        return svc.purchase(
            nation=nation,
            actor_user_id=member.user_id,
            actor_role=member.role,
            research_key=payload.research_key,
        )
    except NationResearchPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except NationResearchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@plugin_router.get("/effects", response_model=NationResearchEffectsResponse)
def get_research_effects(
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> NationResearchEffectsResponse:
    svc = NationResearchService(db, server.id)
    return NationResearchEffectsResponse(nations=svc.resolve_effects_for_server())


@plugin_router.post("/apply-interest")
def apply_research_interest(
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Credit "Центробанк" interest to due treasuries (idempotent per period).

    Called on a timer by the gamesync plugin; only nations past the interest
    period actually get paid, so calling it often is safe.
    """
    return NationResearchService(db, server.id).apply_weekly_interest()
