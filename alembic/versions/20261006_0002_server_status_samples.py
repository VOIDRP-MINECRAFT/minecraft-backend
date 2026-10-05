"""server_status_samples: five-minute snapshots for uptime, charts and the public status

Revision ID: 20261006_0002
Revises: 20261006_0001
Create Date: 2026-10-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261006_0002"
down_revision = "20261006_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_status_samples",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("up", sa.Boolean(), nullable=False),
        sa.Column("online", sa.Integer(), nullable=True),
        sa.Column("max_players", sa.Integer(), nullable=True),
        sa.Column("tps", sa.Float(), nullable=True),
        sa.Column("mspt", sa.Float(), nullable=True),
    )
    op.create_index("ix_server_status_samples_server_at", "server_status_samples", ["server_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_server_status_samples_server_at", table_name="server_status_samples")
    op.drop_table("server_status_samples")
