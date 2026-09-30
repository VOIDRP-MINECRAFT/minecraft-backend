"""server_plugin_reports: heartbeats of our plugins on game servers

Version, server core, which modules run and live monitoring numbers, per server and plugin.

Revision ID: 20260930_0006
Revises: 20260930_0005
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0006"
down_revision = "20260930_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_plugin_reports",
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plugin", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("core", sa.String(160), nullable=True),
        sa.Column("modules", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("server_plugin_reports")
