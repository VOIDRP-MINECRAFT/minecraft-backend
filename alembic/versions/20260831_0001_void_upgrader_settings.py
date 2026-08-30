"""create void_upgrader_settings table

Revision ID: 20260831_0001
Revises: 20260830_0004
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260831_0001"
down_revision = "20260830_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "void_upgrader_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("rtp", sa.Float(), server_default="0.9", nullable=False),
        sa.Column("coins_per_vc", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("min_stake", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_multiplier", sa.Float(), server_default="100", nullable=False),
        sa.Column("max_chance", sa.Float(), server_default="0.9", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_settings_server", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", name="uq_void_upgrader_settings_server"),
    )


def downgrade() -> None:
    op.drop_table("void_upgrader_settings")
