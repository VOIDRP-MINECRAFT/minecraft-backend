"""add nations.is_technical (hide staff/system nations from public rankings)

Revision ID: 20260829_0001
Revises: 20260828_0002
Create Date: 2026-08-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260829_0001"
down_revision = "20260828_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nations",
        sa.Column("is_technical", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Mark the staff/technical "void" nation as technical so it's excluded from rankings.
    op.execute("UPDATE nations SET is_technical = true WHERE lower(slug) = 'void'")


def downgrade() -> None:
    op.drop_column("nations", "is_technical")
