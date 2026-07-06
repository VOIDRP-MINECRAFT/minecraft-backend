"""Alliance game-ui endpoints — view alliance info from the WebGUI browser."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.alliance import Alliance, AllianceMember, AllianceProposal
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount

router = APIRouter(prefix="/game-ui/alliance", tags=["game-ui", "alliance"])


class AllianceMemberInfo(BaseModel):
    nation_slug: str
    nation_title: str
    nation_tag: str
    role: str


class AllianceProposalInfo(BaseModel):
    id: str
    proposal_type: str
    title: str
    description: str | None
    status: str
    yes_count: int
    no_count: int
    veto_count: int
    created_at: Any


class AllianceInfo(BaseModel):
    id: str
    slug: str
    title: str
    tag: str
    alliance_type: str
    description: str | None
    treasury_balance: float
    members: list[AllianceMemberInfo]
    proposals: list[AllianceProposalInfo]
    player_nation_slug: str
    player_role: str


def _find_player_nation(player: PlayerAccount, db: Session) -> tuple[Nation, NationMember] | None:
    member = db.execute(
        select(NationMember).where(NationMember.user_id == player.user_id)
    ).scalar_one_or_none()
    if member is None:
        return None
    nation = db.execute(select(Nation).where(Nation.id == member.nation_id)).scalar_one_or_none()
    if nation is None:
        return None
    return nation, member


@router.get("/my", response_model=AllianceInfo)
def get_my_alliance(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> AllianceInfo:
    result = _find_player_nation(player, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игрок не состоит в государстве.")
    nation, nation_membership = result

    alliance_membership = db.execute(
        select(AllianceMember).where(AllianceMember.nation_id == nation.id)
    ).scalar_one_or_none()
    if alliance_membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Государство не состоит в альянсе.")

    alliance = db.execute(
        select(Alliance).where(Alliance.id == alliance_membership.alliance_id)
    ).scalar_one_or_none()
    if alliance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Альянс не найден.")

    all_members = db.execute(
        select(AllianceMember).where(AllianceMember.alliance_id == alliance.id)
    ).scalars().all()
    member_nation_ids = [m.nation_id for m in all_members]
    member_nations = {
        n.id: n
        for n in db.execute(select(Nation).where(Nation.id.in_(member_nation_ids))).scalars().all()
    }

    members_out: list[AllianceMemberInfo] = []
    for m in all_members:
        n = member_nations.get(m.nation_id)
        if n:
            members_out.append(AllianceMemberInfo(
                nation_slug=n.slug,
                nation_title=n.title,
                nation_tag=n.tag,
                role=m.role,
            ))

    proposals_raw = db.execute(
        select(AllianceProposal)
        .where(AllianceProposal.alliance_id == alliance.id)
        .order_by(AllianceProposal.created_at.desc())
        .limit(20)
    ).scalars().all()

    proposals_out: list[AllianceProposalInfo] = []
    for p in proposals_raw:
        votes = list(p.votes or [])
        proposals_out.append(AllianceProposalInfo(
            id=str(p.id),
            proposal_type=p.proposal_type,
            title=p.title,
            description=p.description,
            status=p.status,
            yes_count=sum(1 for v in votes if str(v.vote).lower() == "yes"),
            no_count=sum(1 for v in votes if str(v.vote).lower() == "no"),
            veto_count=sum(1 for v in votes if str(v.vote).lower() == "veto"),
            created_at=p.created_at,
        ))

    return AllianceInfo(
        id=str(alliance.id),
        slug=alliance.slug,
        title=alliance.title,
        tag=alliance.tag,
        alliance_type=alliance.alliance_type,
        description=alliance.description,
        treasury_balance=float(alliance.treasury_balance or 0),
        members=members_out,
        proposals=proposals_out,
        player_nation_slug=nation.slug,
        player_role=alliance_membership.role,
    )
