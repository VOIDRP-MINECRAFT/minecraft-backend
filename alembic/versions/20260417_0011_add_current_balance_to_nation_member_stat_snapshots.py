"""add current balance to nation member stat snapshots

Revision ID: 20260417_0011
Revises: 20260415_0010
Create Date: 2026-04-17 21:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260417_0011"
down_revision = "20260415_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nation_member_stat_snapshots",
        sa.Column("current_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("nation_member_stat_snapshots", "current_balance")
