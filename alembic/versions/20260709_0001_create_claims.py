"""create land claims (block-anchored, level-expandable)

Revision ID: 20260709_0001
Revises: 20260708_0001
Create Date: 2026-07-09

Adds ``claims`` and ``claim_trusted`` for the anarchy block-claim system. A claim
is anchored at a core block; ``level`` drives how many chunks around the core
chunk it protects. Server-scoped like the rest of the game data.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260709_0001"
down_revision = "20260708_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("dimension", sa.String(length=64), nullable=False),
        sa.Column("core_x", sa.Integer(), nullable=False),
        sa.Column("core_y", sa.Integer(), nullable=False),
        sa.Column("core_z", sa.Integer(), nullable=False),
        sa.Column("core_chunk_x", sa.Integer(), nullable=False),
        sa.Column("core_chunk_z", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
        sa.UniqueConstraint(
            "server_id", "dimension", "core_chunk_x", "core_chunk_z",
            name="uq_claims_server_dim_chunk",
        ),
    )
    op.create_index(op.f("ix_claims_server_id"), "claims", ["server_id"])
    op.create_index(op.f("ix_claims_owner_user_id"), "claims", ["owner_user_id"])
    op.create_index(
        "ix_claims_server_dimension", "claims", ["server_id", "dimension"]
    )

    op.create_table(
        "claim_trusted",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_trusted")),
        sa.UniqueConstraint("claim_id", "user_id", name="uq_claim_trusted_claim_user"),
    )
    op.create_index(op.f("ix_claim_trusted_claim_id"), "claim_trusted", ["claim_id"])
    op.create_index(op.f("ix_claim_trusted_user_id"), "claim_trusted", ["user_id"])


def downgrade() -> None:
    op.drop_table("claim_trusted")
    op.drop_table("claims")
