"""add nation activity logs

Revision ID: 20260412_0006
Revises: 20260412_0005
Create Date: 2026-04-12 21:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260412_0006"
down_revision = "20260412_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nation_activity_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nation_activity_logs_nation_id", "nation_activity_logs", ["nation_id"], unique=False)
    op.create_index("ix_nation_activity_logs_created_at", "nation_activity_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_nation_activity_logs_created_at", table_name="nation_activity_logs")
    op.drop_index("ix_nation_activity_logs_nation_id", table_name="nation_activity_logs")
    op.drop_table("nation_activity_logs")
