from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, ServerScopedMixin


class AllianceType(str, enum.Enum):
    nato = "nato"
    un = "un"
    economic = "economic"


class AllianceMemberRole(str, enum.Enum):
    founder = "founder"
    member = "member"


class AllianceProposalType(str, enum.Enum):
    add_member = "add_member"
    remove_member = "remove_member"
    set_policy = "set_policy"
    treasury_transfer = "treasury_transfer"


class AllianceProposalStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    rejected = "rejected"
    executed = "executed"
    expired = "expired"


class AllianceVoteChoice(str, enum.Enum):
    yes = "yes"
    no = "no"
    veto = "veto"


class Alliance(ServerScopedMixin, Base):
    __tablename__ = "alliances"
    __table_args__ = (
        UniqueConstraint("server_id", "slug", name="uq_alliances_server_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    tag: Mapped[str] = mapped_column(String(12), nullable=False)
    alliance_type: Mapped[str] = mapped_column(String(32), nullable=False, default=AllianceType.un.value)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    founder_nation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nations.id", ondelete="RESTRICT"), nullable=False)

    min_power_required: Mapped[int] = mapped_column(Integer, nullable=False, default=50000)
    transfer_fee_percent: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=5)
    treasury_balance: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    allow_internal_transfers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_joint_defense: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_trade_bonus: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_pvp_protection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    policy_flags_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    members: Mapped[list["AllianceMember"]] = relationship("AllianceMember", back_populates="alliance", cascade="all, delete-orphan")
    proposals: Mapped[list["AllianceProposal"]] = relationship("AllianceProposal", back_populates="alliance", cascade="all, delete-orphan")


class AllianceMember(ServerScopedMixin, Base):
    __tablename__ = "alliance_members"
    __table_args__ = (
        UniqueConstraint("alliance_id", "nation_id", name="uq_alliance_members_alliance_nation"),
        UniqueConstraint("nation_id", name="uq_alliance_members_nation_single_alliance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alliance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alliances.id", ondelete="CASCADE"), index=True, nullable=False)
    nation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nations.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=AllianceMemberRole.member.value)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    alliance: Mapped["Alliance"] = relationship("Alliance", back_populates="members")


class AllianceProposal(ServerScopedMixin, Base):
    __tablename__ = "alliance_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alliance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alliances.id", ondelete="CASCADE"), index=True, nullable=False)
    proposer_nation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nations.id", ondelete="CASCADE"), nullable=False)

    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AllianceProposalStatus.open.value)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    execution_result: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    alliance: Mapped["Alliance"] = relationship("Alliance", back_populates="proposals")
    votes: Mapped[list["AllianceVote"]] = relationship("AllianceVote", back_populates="proposal", cascade="all, delete-orphan")


class AllianceVote(ServerScopedMixin, Base):
    __tablename__ = "alliance_votes"
    __table_args__ = (
        UniqueConstraint("proposal_id", "nation_id", name="uq_alliance_votes_proposal_nation"),
        CheckConstraint("vote IN ('yes','no','veto')", name="ck_alliance_votes_choice"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alliance_proposals.id", ondelete="CASCADE"), index=True, nullable=False)
    nation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nations.id", ondelete="CASCADE"), nullable=False)
    vote: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    proposal: Mapped["AllianceProposal"] = relationship("AllianceProposal", back_populates="votes")
