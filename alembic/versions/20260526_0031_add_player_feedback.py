"""add player_feedback table

Revision ID: 20260526_0031
Revises: 20260524_0030
Create Date: 2026-05-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0031"
down_revision = "20260524_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_player_feedback_user_id", "player_feedback", ["user_id"])
    op.create_index("ix_player_feedback_type", "player_feedback", ["type"])


def downgrade() -> None:
    op.drop_index("ix_player_feedback_type", table_name="player_feedback")
    op.drop_index("ix_player_feedback_user_id", table_name="player_feedback")
    op.drop_table("player_feedback")