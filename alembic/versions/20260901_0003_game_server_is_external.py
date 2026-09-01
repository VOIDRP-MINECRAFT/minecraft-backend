"""game_servers: is_external flag (third-party catalogue servers)

Revision ID: 20260901_0003
Revises: 20260901_0002
Create Date: 2026-09-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260901_0003"
down_revision = "20260901_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("is_external", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("game_servers", "is_external")
