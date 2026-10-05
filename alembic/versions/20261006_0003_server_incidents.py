"""server_incidents: outages and slowdowns, opened and closed by integration_watch

Revision ID: 20261006_0003
Revises: 20261006_0002
Create Date: 2026-10-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261006_0003"
down_revision = "20261006_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_incidents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.String(300), nullable=True),
    )
    op.create_index("ix_server_incidents_server_started", "server_incidents", ["server_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_server_incidents_server_started", table_name="server_incidents")
    op.drop_table("server_incidents")
