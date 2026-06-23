from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AllianceTargetNationSummary(BaseModel):
    id: UUID
    slug: str
    title: str
    tag: str
    accent_color: str | None = None
    icon_url: str | None = None
    icon_preview_url: str | None = None


class AllianceMemberRead(BaseModel):
    id: UUID
    nation: AllianceTargetNationSummary
    role: str
    joined_at: datetime


class AllianceViewerStateRead(BaseModel):
    has_nation: bool = False
    nation_id: UUID | None = None
    nation_slug: str | None = None
    nation_title: str | None = None
    nation_role: str | None = None
    nation_can_manage: bool = False
    current_alliance_id: UUID | None = None
    current_alliance_slug: str | None = None
    current_alliance_title: str | None = None
    is_member: bool = False
    is_founder_nation: bool = False
    is_read_only_member: bool = False
    can_join: bool = False
    can_apply: bool = False
    has_pending_application: bool = False
    can_leave: bool = False
    can_manage_alliance: bool = False
    can_manage_policies: bool = False
    can_create_proposals: bool = False
    can_vote: bool = False
    can_transfer: bool = False


class AllianceRead(BaseModel):
    id: UUID
    slug: str
    title: str
    tag: str
    alliance_type: str
    description: str | None = None
    founder_nation_id: UUID
    min_power_required: int
    transfer_fee_percent: Decimal
    treasury_balance: Decimal
    allow_internal_transfers: bool
    allow_joint_defense: bool
    allow_trade_bonus: bool
    allow_pvp_protection: bool
    policy_flags_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    members_count: int = 0
    members: list[AllianceMemberRead] = Field(default_factory=list)
    viewer: AllianceViewerStateRead = Field(default_factory=AllianceViewerStateRead)


class AllianceListResponse(BaseModel):
    total: int
    items: list[AllianceRead]


class AllianceCreateRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=64)
    title: str = Field(min_length=3, max_length=80)
    tag: str = Field(min_length=2, max_length=12)
    alliance_type: str = Field(default="un")
    description: str | None = Field(default=None, max_length=500)


class AlliancePolicyUpdateRequest(BaseModel):
    transfer_fee_percent: Decimal | None = None
    allow_internal_transfers: bool | None = None
    allow_joint_defense: bool | None = None
    allow_trade_bonus: bool | None = None
    allow_pvp_protection: bool | None = None
    policy_flags_json: dict[str, Any] | None = None


class AllianceJoinRequest(BaseModel):
    alliance_slug: str


class AllianceActionResponse(BaseModel):
    message: str
    alliance_slug: str | None = None
    dissolved: bool = False


class AllianceProposalCreateRequest(BaseModel):
    proposal_type: str
    title: str
    description: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)


class AllianceVoteRequest(BaseModel):
    vote: str
    comment: str | None = Field(default=None, max_length=300)


class AllianceProposalVoteRead(BaseModel):
    id: UUID
    nation_id: UUID
    vote: str
    comment: str | None = None
    created_at: datetime


class AllianceProposalVoteSummaryRead(BaseModel):
    yes: int = 0
    no: int = 0
    veto: int = 0
    total: int = 0


class AllianceProposalRead(BaseModel):
    id: UUID
    alliance_id: UUID
    proposer_nation_id: UUID
    proposal_type: str
    status: str
    title: str
    description: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    execution_status: str = "pending"
    execution_result: str | None = None
    executed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    vote_summary: AllianceProposalVoteSummaryRead = Field(default_factory=AllianceProposalVoteSummaryRead)
    votes: list[AllianceProposalVoteRead] = Field(default_factory=list)


class AllianceProposalListResponse(BaseModel):
    total: int
    items: list[AllianceProposalRead]


class AllianceTransferRequest(BaseModel):
    from_nation_slug: str
    to_nation_slug: str
    amount: Decimal = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)
