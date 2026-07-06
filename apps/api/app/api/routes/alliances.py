from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user, get_optional_current_user
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.alliance import Alliance, AllianceMember, AllianceProposal, AllianceProposalStatus
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.user import User
from apps.api.app.schemas.alliance import (
    AllianceActionResponse,
    AllianceCreateRequest,
    AllianceJoinRequest,
    AllianceListResponse,
    AlliancePolicyUpdateRequest,
    AllianceProposalCreateRequest,
    AllianceProposalListResponse,
    AllianceProposalRead,
    AllianceRead,
    AllianceTransferRequest,
    AllianceVoteRequest,
)
from apps.api.app.services.alliance_service import (
    AllianceNotFoundError,
    AlliancePermissionError,
    AllianceService,
    AllianceValidationError,
)

router = APIRouter(prefix="/alliances", tags=["alliances"])


def get_alliance_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> AllianceService:
    return AllianceService(session, server.id)


def _get_current_user_nation(session: Session, current_user: User) -> Nation | None:
    return session.execute(
        select(Nation)
        .join(NationMember, NationMember.nation_id == Nation.id)
        .where(NationMember.user_id == current_user.id)
    ).scalar_one_or_none()


def _get_current_user_nation_membership(session: Session, current_user: User) -> tuple[Nation | None, NationMember | None]:
    membership = session.execute(
        select(NationMember)
        .options(joinedload(NationMember.nation))
        .where(NationMember.user_id == current_user.id)
    ).unique().scalar_one_or_none()
    return (membership.nation if membership is not None else None, membership)


def _build_viewer_state(session: Session, alliance: Alliance, current_user: User | None) -> dict:
    if current_user is None:
        return {
            "has_nation": False,
            "is_member": False,
            "is_founder_nation": False,
            "is_read_only_member": False,
            "can_join": False,
            "can_leave": False,
            "can_manage_alliance": False,
            "can_manage_policies": False,
            "can_create_proposals": False,
            "can_vote": False,
            "can_transfer": False,
        }

    nation, membership = _get_current_user_nation_membership(session, current_user)
    if nation is None or membership is None:
        return {
            "has_nation": False,
            "is_member": False,
            "is_founder_nation": False,
            "is_read_only_member": False,
            "can_join": False,
            "can_leave": False,
            "can_manage_alliance": False,
            "can_manage_policies": False,
            "can_create_proposals": False,
            "can_vote": False,
            "can_transfer": False,
        }

    nation_can_manage = membership.role in {"leader", "officer"}
    current_alliance_member = session.execute(
        select(AllianceMember).where(AllianceMember.nation_id == nation.id)
    ).scalar_one_or_none()

    current_alliance = None
    if current_alliance_member is not None:
        current_alliance = session.get(Alliance, current_alliance_member.alliance_id)

    is_member = current_alliance_member is not None and current_alliance_member.alliance_id == alliance.id
    is_founder_nation = is_member and (
        current_alliance_member.role == "founder" or alliance.founder_nation_id == nation.id
    )

    can_apply = nation_can_manage and current_alliance_member is None and not is_member

    has_pending_application = False
    if can_apply:
        pending = session.execute(
            select(AllianceProposal).where(
                AllianceProposal.alliance_id == alliance.id,
                AllianceProposal.proposal_type == "add_member",
                AllianceProposal.status == AllianceProposalStatus.open.value,
            )
        ).scalars().all()
        for p in pending:
            if (p.payload_json or {}).get("nation_slug") == nation.slug:
                has_pending_application = True
                break

    return {
        "has_nation": True,
        "nation_id": nation.id,
        "nation_slug": nation.slug,
        "nation_title": nation.title,
        "nation_role": membership.role,
        "nation_can_manage": nation_can_manage,
        "current_alliance_id": current_alliance.id if current_alliance is not None else None,
        "current_alliance_slug": current_alliance.slug if current_alliance is not None else None,
        "current_alliance_title": current_alliance.title if current_alliance is not None else None,
        "is_member": is_member,
        "is_founder_nation": is_founder_nation,
        "is_read_only_member": is_member and not nation_can_manage,
        "can_join": False,
        "can_apply": can_apply,
        "has_pending_application": has_pending_application,
        "can_leave": nation_can_manage and is_member,
        "can_manage_alliance": nation_can_manage and is_member,
        "can_manage_policies": nation_can_manage and is_member and is_founder_nation,
        "can_create_proposals": nation_can_manage and is_member,
        "can_vote": nation_can_manage and is_member,
        "can_transfer": nation_can_manage and is_member and bool(alliance.allow_internal_transfers),
    }


def _serialize_nation(nation: Nation) -> dict:
    return {
        "id": nation.id,
        "slug": nation.slug,
        "title": nation.title,
        "tag": nation.tag,
        "accent_color": getattr(nation, "accent_color", None),
        "icon_url": getattr(nation, "icon_url", None),
        "icon_preview_url": getattr(nation, "icon_preview_url", None),
    }


def _serialize_alliance(session: Session, alliance: Alliance, current_user: User | None = None) -> dict:
    nation_ids = [item.nation_id for item in getattr(alliance, "members", []) or []]
    nations = session.execute(select(Nation).where(Nation.id.in_(nation_ids))).scalars().all() if nation_ids else []
    nation_lookup = {item.id: item for item in nations}
    members = []
    for item in getattr(alliance, "members", []) or []:
        nation = nation_lookup.get(item.nation_id)
        if nation is None:
            continue
        members.append({"id": item.id, "nation": _serialize_nation(nation), "role": item.role, "joined_at": item.joined_at})

    return {
        "id": alliance.id,
        "slug": alliance.slug,
        "title": alliance.title,
        "tag": alliance.tag,
        "alliance_type": alliance.alliance_type,
        "description": alliance.description,
        "founder_nation_id": alliance.founder_nation_id,
        "min_power_required": alliance.min_power_required,
        "transfer_fee_percent": alliance.transfer_fee_percent,
        "treasury_balance": alliance.treasury_balance,
        "allow_internal_transfers": alliance.allow_internal_transfers,
        "allow_joint_defense": alliance.allow_joint_defense,
        "allow_trade_bonus": alliance.allow_trade_bonus,
        "allow_pvp_protection": alliance.allow_pvp_protection,
        "policy_flags_json": alliance.policy_flags_json or {},
        "created_at": alliance.created_at,
        "updated_at": alliance.updated_at,
        "members_count": len(members),
        "members": members,
        "viewer": _build_viewer_state(session, alliance, current_user),
    }


def _serialize_transaction(item: NationTreasuryTransaction) -> dict:
    return {
        "id": item.id,
        "transaction_type": item.transaction_type,
        "nation_id": item.nation_id,
        "counterparty_nation_id": item.counterparty_nation_id,
        "alliance_id": item.alliance_id,
        "created_by_user_id": item.created_by_user_id,
        "gross_amount": item.gross_amount,
        "fee_amount": item.fee_amount,
        "net_amount": item.net_amount,
        "comment": item.comment,
        "metadata_json": item.metadata_json or {},
        "created_at": item.created_at,
    }


def _serialize_proposal(item: AllianceProposal) -> dict:
    votes = list(item.votes or [])
    yes_count = sum(1 for vote in votes if str(vote.vote).lower() == "yes")
    no_count = sum(1 for vote in votes if str(vote.vote).lower() == "no")
    veto_count = sum(1 for vote in votes if str(vote.vote).lower() == "veto")

    return {
        "id": item.id,
        "alliance_id": item.alliance_id,
        "proposer_nation_id": item.proposer_nation_id,
        "proposal_type": item.proposal_type,
        "status": item.status,
        "title": item.title,
        "description": item.description,
        "payload_json": item.payload_json or {},
        "execution_status": getattr(item, "execution_status", "pending"),
        "execution_result": getattr(item, "execution_result", None),
        "executed_at": getattr(item, "executed_at", None),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "vote_summary": {
            "yes": yes_count,
            "no": no_count,
            "veto": veto_count,
            "total": len(votes),
        },
        "votes": [
            {
                "id": vote.id,
                "nation_id": vote.nation_id,
                "vote": vote.vote,
                "comment": vote.comment,
                "created_at": vote.created_at,
            }
            for vote in (item.votes or [])
        ],
    }


@router.get("", response_model=AllianceListResponse)
def list_alliances(
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    service: Annotated[AllianceService, Depends(get_alliance_service)],
) -> AllianceListResponse:
    items = service.list_alliances()
    payload = [_serialize_alliance(service.session, item, current_user) for item in items]
    return AllianceListResponse(total=len(payload), items=payload)


@router.get("/{slug}", response_model=AllianceRead)
def get_alliance(
    slug: str,
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    service: Annotated[AllianceService, Depends(get_alliance_service)],
) -> AllianceRead:
    try:
        item = service.get_by_slug(slug)
        return AllianceRead.model_validate(_serialize_alliance(service.session, item, current_user))
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("", response_model=AllianceRead)
def create_alliance(payload: AllianceCreateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceRead:
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    try:
        item = service.create_alliance(
            current_user=current_user,
            source_nation=source_nation,
            slug=payload.slug,
            title=payload.title,
            tag=payload.tag,
            alliance_type=payload.alliance_type,
            description=payload.description,
        )
        return AllianceRead.model_validate(_serialize_alliance(service.session, item, current_user))
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/join", response_model=AllianceRead)
def join_alliance(payload: AllianceJoinRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceRead:
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    try:
        item = service.join_alliance(current_user=current_user, source_nation=source_nation, alliance_slug=payload.alliance_slug)
        return AllianceRead.model_validate(_serialize_alliance(service.session, item, current_user))
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/leave", response_model=AllianceActionResponse)
def leave_alliance(current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceActionResponse:
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    try:
        result = service.leave_alliance(current_user=current_user, source_nation=source_nation)
        return AllianceActionResponse.model_validate(result)
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{slug}/policies", response_model=AllianceRead)
def update_policies(slug: str, payload: AlliancePolicyUpdateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceRead:
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    try:
        item = service.update_policies(
            current_user=current_user,
            source_nation=source_nation,
            alliance_slug=slug,
            data=payload.model_dump(exclude_none=True),
        )
        return AllianceRead.model_validate(_serialize_alliance(service.session, item, current_user))
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{slug}/proposals", response_model=AllianceProposalListResponse)
def list_proposals(slug: str, service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceProposalListResponse:
    try:
        items = service.list_proposals(slug)
        return AllianceProposalListResponse(total=len(items), items=[AllianceProposalRead.model_validate(_serialize_proposal(item)) for item in items])
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{slug}/proposals", response_model=AllianceProposalRead)
def create_proposal(slug: str, payload: AllianceProposalCreateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceProposalRead:
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    try:
        proposal = service.create_proposal(
            current_user=current_user,
            source_nation=source_nation,
            alliance_slug=slug,
            proposal_type=payload.proposal_type,
            title=payload.title,
            description=payload.description,
            payload_json=payload.payload_json,
        )
        return AllianceProposalRead.model_validate(_serialize_proposal(proposal))
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/vote", response_model=AllianceProposalRead)
def vote_on_proposal(proposal_id: UUID, payload: AllianceVoteRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]) -> AllianceProposalRead:
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    proposal_obj = service.session.execute(select(AllianceProposal).where(AllianceProposal.id == proposal_id)).scalar_one_or_none()
    if proposal_obj is None:
        raise HTTPException(status_code=404, detail="Предложение не найдено.")
    try:
        proposal = service.vote_on_proposal(
            current_user=current_user,
            source_nation=source_nation,
            proposal_id=proposal_id,
            vote=payload.vote,
            comment=payload.comment,
        )
        return AllianceProposalRead.model_validate(_serialize_proposal(proposal))
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{slug}/transfer")
def transfer_between_members(slug: str, payload: AllianceTransferRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]):
    source_nation = _get_current_user_nation(service.session, current_user)
    if source_nation is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    try:
        return service.transfer_between_members(
            current_user=current_user,
            source_nation=source_nation,
            alliance_slug=slug,
            from_nation_slug=payload.from_nation_slug,
            to_nation_slug=payload.to_nation_slug,
            amount=payload.amount,
            comment=payload.comment,
        )
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AllianceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AlliancePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{slug}/apply")
def apply_to_alliance(slug: str, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[AllianceService, Depends(get_alliance_service)]):
    """Nation leader submits a join application → creates an open add_member proposal for alliance members to vote on."""
    nation, membership = _get_current_user_nation_membership(service.session, current_user)
    if nation is None or membership is None:
        raise HTTPException(status_code=400, detail="Текущий пользователь не состоит в государстве.")
    if membership.role not in {"leader", "officer"}:
        raise HTTPException(status_code=403, detail="Только лидер или офицер государства может подать заявку.")

    existing_member = service.session.execute(
        select(AllianceMember).where(AllianceMember.nation_id == nation.id)
    ).scalar_one_or_none()
    if existing_member is not None:
        raise HTTPException(status_code=400, detail="Государство уже состоит в альянсе.")

    try:
        alliance = service.get_by_slug(slug)
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
        server_id=service.server_id,
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
        actor_user_id=current_user.id,
        message=f"Государство подало заявку на вступление в альянс {alliance.title}.",
        metadata={"alliance_slug": alliance.slug},
    )
    service.session.commit()
    service.session.refresh(proposal)
    return {"message": f"Заявка в альянс «{alliance.title}» подана. Участники проголосуют за принятие.", "proposal_id": str(proposal.id)}


@router.get("/{slug}/transactions")
def list_alliance_transactions(slug: str, service: Annotated[AllianceService, Depends(get_alliance_service)]):
    try:
        items = service.list_transactions(slug)
        return {"total": len(items), "items": [_serialize_transaction(item) for item in items]}
    except AllianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



