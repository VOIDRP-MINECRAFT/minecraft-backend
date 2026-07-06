from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.alliance import (
    Alliance,
    AllianceMember,
    AllianceProposal,
    AllianceProposalStatus,
)
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.services.alliance_service import (
    AllianceNotFoundError,
    AlliancePermissionError,
    AllianceService,
    AllianceValidationError,
)
from apps.api.app.utils.normalization import normalize_minecraft_nickname

router = APIRouter(prefix="/game-sync/alliances", tags=["game-sync-alliances"])


class GameAllianceApplyRequest(BaseModel):
    minecraft_nickname: str
    alliance_slug: str


class GameAllianceLeaveRequest(BaseModel):
    minecraft_nickname: str


class GameAllianceVoteRequest(BaseModel):
    minecraft_nickname: str
    vote: str
    comment: str | None = None


class GameAllianceKickRequest(BaseModel):
    minecraft_nickname: str
    target_nation_slug: str


def _get_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> AllianceService:
    return AllianceService(session, server.id)


def _lookup(session: Session, minecraft_nickname: str):
    """Returns (user, nation, nation_member) or raises HTTPException."""
    _, normalized = normalize_minecraft_nickname(minecraft_nickname)
    account = session.execute(
        select(PlayerAccount)
        .options(joinedload(PlayerAccount.user))
        .where(PlayerAccount.minecraft_nickname_normalized == normalized)
    ).scalar_one_or_none()
    if account is None or account.user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден.")
    membership = session.execute(
        select(NationMember).where(NationMember.user_id == account.user.id)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=400, detail="Игрок не состоит в государстве.")
    nation = session.get(Nation, membership.nation_id)
    if nation is None:
        raise HTTPException(status_code=400, detail="Государство не найдено.")
    return account.user, nation, membership


@router.get("/pvp-map", dependencies=[Depends(require_game_auth_secret)])
def get_pvp_map(service: Annotated[AllianceService, Depends(_get_service)]):
    """Returns {nation_slug: alliance_slug} for alliances with pvp_protection=True.
    Plugin caches this to block PvP between allied nations."""
    alliances = service.session.execute(
        select(Alliance).where(Alliance.allow_pvp_protection == True)  # noqa: E712
    ).scalars().all()
    result: dict[str, str] = {}
    for a in alliances:
        members = service.session.execute(
            select(AllianceMember).where(AllianceMember.alliance_id == a.id)
        ).scalars().all()
        for m in members:
            nation = service.session.get(Nation, m.nation_id)
            if nation is not None:
                result[nation.slug] = a.slug
    return result


@router.post("/apply", dependencies=[Depends(require_game_auth_secret)])
def apply_to_alliance(
    payload: GameAllianceApplyRequest,
    service: Annotated[AllianceService, Depends(_get_service)],
):
    """Nation leader submits a join application → creates an open add_member proposal.
    Alliance members then vote to accept or reject."""
    user, nation, membership = _lookup(service.session, payload.minecraft_nickname)
    if membership.role not in {"leader", "officer"}:
        raise HTTPException(status_code=403, detail="Только лидер или офицер государства может подать заявку.")

    existing_member = service.session.execute(
        select(AllianceMember).where(AllianceMember.nation_id == nation.id)
    ).scalar_one_or_none()
    if existing_member is not None:
        raise HTTPException(status_code=400, detail="Государство уже состоит в альянсе.")

    try:
        alliance = service.get_by_slug(payload.alliance_slug)
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    duplicates = service.session.execute(
        select(AllianceProposal).where(
            AllianceProposal.alliance_id == alliance.id,
            AllianceProposal.proposal_type == "add_member",
            AllianceProposal.status == AllianceProposalStatus.open.value,
        )
    ).scalars().all()
    for p in duplicates:
        if (p.payload_json or {}).get("nation_slug") == nation.slug:
            raise HTTPException(status_code=400, detail="Заявка от этого государства уже на рассмотрении.")

    proposal = AllianceProposal(
        alliance_id=alliance.id,
        proposer_nation_id=nation.id,
        proposal_type="add_member",
        status=AllianceProposalStatus.open.value,
        title=f"Принятие государства {nation.title}",
        description=f"Государство {nation.title} подало заявку на вступление в альянс.",
        payload_json={"nation_slug": nation.slug},
        execution_status="pending",
    )
    service.session.add(proposal)
    service.activity.record(
        nation_id=nation.id,
        event_type="alliance_application_submitted",
        actor_user_id=user.id,
        message=f"Государство подало заявку на вступление в альянс {alliance.title}.",
        metadata={"alliance_slug": alliance.slug},
    )
    service.session.commit()
    service.session.refresh(proposal)
    return {
        "message": f"Заявка в альянс «{alliance.title}» подана. Ожидайте решения участников.",
        "proposal_id": str(proposal.id),
    }


@router.post("/leave", dependencies=[Depends(require_game_auth_secret)])
def leave_alliance(
    payload: GameAllianceLeaveRequest,
    service: Annotated[AllianceService, Depends(_get_service)],
):
    user, nation, membership = _lookup(service.session, payload.minecraft_nickname)
    if membership.role not in {"leader", "officer"}:
        raise HTTPException(status_code=403, detail="Только лидер или офицер может покинуть альянс.")
    try:
        return service.leave_alliance(current_user=user, source_nation=nation)
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (AllianceValidationError, AllianceNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/proposals", dependencies=[Depends(require_game_auth_secret)])
def get_proposals(
    minecraft_nickname: Annotated[str, Query()],
    service: Annotated[AllianceService, Depends(_get_service)],
):
    """Returns open proposals for the calling player's current alliance."""
    user, nation, membership = _lookup(service.session, minecraft_nickname)
    alliance_member = service.session.execute(
        select(AllianceMember).where(AllianceMember.nation_id == nation.id)
    ).scalar_one_or_none()
    if alliance_member is None:
        raise HTTPException(status_code=400, detail="Государство не состоит в альянсе.")
    alliance = service.session.get(Alliance, alliance_member.alliance_id)
    if alliance is None:
        raise HTTPException(status_code=404, detail="Альянс не найден.")

    proposals = service.session.execute(
        select(AllianceProposal)
        .options(joinedload(AllianceProposal.votes))
        .where(
            AllianceProposal.alliance_id == alliance.id,
            AllianceProposal.status == AllianceProposalStatus.open.value,
        )
        .order_by(AllianceProposal.created_at.desc())
    ).unique().scalars().all()

    def _fmt(p: AllianceProposal) -> dict:
        votes = list(p.votes or [])
        my_vote = next((v.vote for v in votes if v.nation_id == nation.id), None)
        return {
            "id": str(p.id),
            "proposal_type": p.proposal_type,
            "title": p.title,
            "description": p.description,
            "payload_json": p.payload_json or {},
            "yes": sum(1 for v in votes if v.vote == "yes"),
            "no": sum(1 for v in votes if v.vote == "no"),
            "veto": sum(1 for v in votes if v.vote == "veto"),
            "my_vote": my_vote,
            "created_at": p.created_at.isoformat(),
        }

    return {
        "alliance_slug": alliance.slug,
        "alliance_title": alliance.title,
        "proposals": [_fmt(p) for p in proposals],
    }


@router.post("/proposals/{proposal_id}/vote", dependencies=[Depends(require_game_auth_secret)])
def vote_on_proposal(
    proposal_id: UUID,
    payload: GameAllianceVoteRequest,
    service: Annotated[AllianceService, Depends(_get_service)],
):
    user, nation, membership = _lookup(service.session, payload.minecraft_nickname)
    if membership.role not in {"leader", "officer"}:
        raise HTTPException(status_code=403, detail="Только лидер или офицер может голосовать.")
    try:
        proposal = service.vote_on_proposal(
            current_user=user,
            source_nation=nation,
            proposal_id=proposal_id,
            vote=payload.vote,
            comment=payload.comment,
        )
        return {"message": "Голос принят.", "proposal_id": str(proposal.id), "status": proposal.status}
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/kick", dependencies=[Depends(require_game_auth_secret)])
def propose_kick(
    payload: GameAllianceKickRequest,
    service: Annotated[AllianceService, Depends(_get_service)],
):
    """Creates a remove_member proposal to kick a nation from the alliance."""
    user, nation, membership = _lookup(service.session, payload.minecraft_nickname)
    alliance_member = service.session.execute(
        select(AllianceMember).where(AllianceMember.nation_id == nation.id)
    ).scalar_one_or_none()
    if alliance_member is None:
        raise HTTPException(status_code=400, detail="Вы не состоите в альянсе.")
    alliance = service.session.get(Alliance, alliance_member.alliance_id)
    if alliance is None:
        raise HTTPException(status_code=404, detail="Альянс не найден.")

    try:
        target_nation = service._get_nation_by_slug(payload.target_nation_slug)
    except AllianceValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    target_am = service.session.execute(
        select(AllianceMember).where(
            AllianceMember.alliance_id == alliance.id,
            AllianceMember.nation_id == target_nation.id,
        )
    ).scalar_one_or_none()
    if target_am is None:
        raise HTTPException(status_code=400, detail="Указанное государство не состоит в вашем альянсе.")
    if target_nation.id == nation.id:
        raise HTTPException(status_code=400, detail="Нельзя предложить исключить своё государство. Используйте /alliance leave.")

    try:
        proposal = service.create_proposal(
            current_user=user,
            source_nation=nation,
            alliance_slug=alliance.slug,
            proposal_type="remove_member",
            title=f"Исключение государства {target_nation.title}",
            description=f"Предложение об исключении государства {target_nation.title} из альянса.",
            payload_json={"nation_slug": payload.target_nation_slug},
        )
        return {"message": f"Предложение об исключении «{target_nation.title}» создано.", "proposal_id": str(proposal.id)}
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
