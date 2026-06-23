"""add alliance foundation

Revision ID: 20260413_0007
Revises: 20260412_0006
Create Date: 2026-04-13 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260413_0007"
down_revision = "20260412_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alliances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("tag", sa.String(length=12), nullable=False),
        sa.Column("alliance_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("founder_nation_id", sa.Uuid(), nullable=False),
        sa.Column("min_power_required", sa.Integer(), nullable=False, server_default="50000"),
        sa.Column("transfer_fee_percent", sa.Numeric(10, 2), nullable=False, server_default="5"),
        sa.Column("treasury_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("allow_internal_transfers", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_joint_defense", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_trade_bonus", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_pvp_protection", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_flags_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["founder_nation_id"], ["nations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alliances_slug", "alliances", ["slug"], unique=True)

    op.create_table(
        "alliance_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alliance_id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["alliance_id"], ["alliances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alliance_id", "nation_id", name="uq_alliance_members_alliance_nation"),
        sa.UniqueConstraint("nation_id", name="uq_alliance_members_nation_single_alliance"),
    )
    op.create_index("ix_alliance_members_alliance_id", "alliance_members", ["alliance_id"], unique=False)
    op.create_index("ix_alliance_members_nation_id", "alliance_members", ["nation_id"], unique=False)

    op.create_table(
        "alliance_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alliance_id", sa.Uuid(), nullable=False),
        sa.Column("proposer_nation_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["alliance_id"], ["alliances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposer_nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alliance_proposals_alliance_id", "alliance_proposals", ["alliance_id"], unique=False)

    op.create_table(
        "alliance_votes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("vote", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["alliance_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "nation_id", name="uq_alliance_votes_proposal_nation"),
        sa.CheckConstraint("vote in ('yes','no','veto')", name="ck_alliance_votes_choice"),
    )
    op.create_index("ix_alliance_votes_proposal_id", "alliance_votes", ["proposal_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alliance_votes_proposal_id", table_name="alliance_votes")
    op.drop_table("alliance_votes")

    op.drop_index("ix_alliance_proposals_alliance_id", table_name="alliance_proposals")
    op.drop_table("alliance_proposals")

    op.drop_index("ix_alliance_members_nation_id", table_name="alliance_members")
    op.drop_index("ix_alliance_members_alliance_id", table_name="alliance_members")
    op.drop_table("alliance_members")

    op.drop_index("ix_alliances_slug", table_name="alliances")
    op.drop_table("alliances")
