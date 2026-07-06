"""map each game server to an EasyDonate server id

Revision ID: 20260707_0003
Revises: 20260707_0002
Create Date: 2026-07-07

Adds ``easydonate_server_id`` to ``game_servers`` so donation products/commands
for a purchase are delivered to the right server's EasyDonate shop. Nullable —
null falls back to the global default (settings.easydonate_server_id).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260707_0003"
down_revision = "20260707_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("easydonate_server_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("game_servers", "easydonate_server_id")
