"""battlepass_progress: prestige column (public status)

Revision ID: 20260831_0005
Revises: 20260831_0004
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260831_0005"
down_revision = "20260831_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("battlepass_progress", sa.Column("prestige", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("battlepass_progress", "prestige")
