"""extend alliance proposals execution

Revision ID: 20260414_0009
Revises: 20260413_0008
Create Date: 2026-04-14 23:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260414_0009"
down_revision = "20260413_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alliance_proposals", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alliance_proposals", sa.Column("execution_status", sa.String(length=32), nullable=False, server_default="pending"))
    op.add_column("alliance_proposals", sa.Column("execution_result", sa.String(length=500), nullable=True))
    op.create_index("ix_alliance_proposals_execution_status", "alliance_proposals", ["execution_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alliance_proposals_execution_status", table_name="alliance_proposals")
    op.drop_column("alliance_proposals", "execution_result")
    op.drop_column("alliance_proposals", "execution_status")
    op.drop_column("alliance_proposals", "executed_at")
