"""create bounties (diamond price-on-head for the abyss anarchy server)

Revision ID: 20260713_0001
Revises: 20260709_0002
Create Date: 2026-07-13

Adds ``bounties``: each row is one diamond reward pledged for killing a target.
Placements stack per target and are all claimed together on a kill. Diamonds are
physical (handled by the mod); the backend only tracks pledged amounts. Server-scoped.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0001"
down_revision = "20260709_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bounties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("target_nick", sa.String(length=16), nullable=False),
        sa.Column("target_nick_normalized", sa.String(length=16), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("placed_by_nick", sa.String(length=16), nullable=False),
        sa.Column("placed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("killer_nick", sa.String(length=16), nullable=True),
        sa.Column("killer_user_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["placed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["killer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bounties")),
    )
    op.create_index(op.f("ix_bounties_server_id"), "bounties", ["server_id"])
    op.create_index(op.f("ix_bounties_target_user_id"), "bounties", ["target_user_id"])
    op.create_index(op.f("ix_bounties_placed_by_user_id"), "bounties", ["placed_by_user_id"])
    op.create_index(op.f("ix_bounties_killer_user_id"), "bounties", ["killer_user_id"])
    op.create_index(
        "ix_bounties_server_target_status",
        "bounties",
        ["server_id", "target_nick_normalized", "status"],
    )


def downgrade() -> None:
    op.drop_table("bounties")
