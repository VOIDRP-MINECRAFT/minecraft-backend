"""donations per server: each server's own EasyDonate shop key

``game_servers.easydonate_shop_key`` (nullable). Empty → the global key from settings,
as before, so nothing changes until a key is set for a server.

Revision ID: 20260929_0009
Revises: 20260929_0008
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260929_0009"
down_revision = "20260929_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("easydonate_shop_key", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("game_servers", "easydonate_shop_key")
