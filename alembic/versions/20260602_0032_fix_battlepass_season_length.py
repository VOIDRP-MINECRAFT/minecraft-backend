"""fix battlepass_progress season column length (8->32)

Revision ID: 20260602_0032
Revises: 20260526_0031
Create Date: 2026-06-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260602_0032"
down_revision = "20260526_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "battlepass_progress",
        "season",
        type_=sa.String(32),
        existing_type=sa.String(8),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "battlepass_progress",
        "season",
        type_=sa.String(8),
        existing_type=sa.String(32),
        existing_nullable=False,
    )
