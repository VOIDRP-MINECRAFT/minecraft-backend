"""game_servers.integration_settings: auto-update of our plugins by VoidRpPerms

Revision ID: 20261005_0005
Revises: 20261005_0004
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261005_0005"
down_revision = "20261005_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("integration_settings", postgresql.JSONB(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("game_servers", "integration_settings")
