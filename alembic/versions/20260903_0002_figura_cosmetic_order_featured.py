"""figura_cosmetics: sort_order + featured

Revision ID: 20260903_0002
Revises: 20260903_0001
Create Date: 2026-09-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260903_0002"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("figura_cosmetics", sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False))
    op.add_column("figura_cosmetics", sa.Column("featured", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("figura_cosmetics", "featured")
    op.drop_column("figura_cosmetics", "sort_order")
