"""battlepass_rewards: admin-editable per-season reward slots

Revision ID: 20260902_0001
Revises: 20260901_0003
Create Date: 2026-09-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260902_0001"
down_revision = "20260901_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "battlepass_rewards",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("game_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season", sa.String(length=32), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("track", sa.String(length=8), nullable=False),
        sa.Column("reward_type", sa.String(length=16), nullable=False),
        sa.Column("command", sa.String(length=512), nullable=True),
        sa.Column("material", sa.String(length=64), nullable=True),
        sa.Column("item_key", sa.String(length=128), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("icon", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "season", "level", "track", name="uq_battlepass_rewards_slot"),
    )
    op.create_index("ix_battlepass_rewards_server_id", "battlepass_rewards", ["server_id"])
    op.create_index("ix_battlepass_rewards_season", "battlepass_rewards", ["season"])


def downgrade() -> None:
    op.drop_index("ix_battlepass_rewards_season", table_name="battlepass_rewards")
    op.drop_index("ix_battlepass_rewards_server_id", table_name="battlepass_rewards")
    op.drop_table("battlepass_rewards")
