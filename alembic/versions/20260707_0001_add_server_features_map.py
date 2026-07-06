"""add per-server map_url and features flags

Revision ID: 20260707_0001
Revises: 20260706_0002
Create Date: 2026-07-07

Adds ``map_url`` (web map link) and ``features`` (JSONB capability flags) to
``game_servers``. Existing rows are backfilled with all features enabled so the
default server keeps every launcher/site tab.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260707_0001"
down_revision = "20260706_0002"
branch_labels = None
depends_on = None

_ALL_FEATURES = (
    '{"nations": true, "economy": true, "shop": true, "alliances": true, '
    '"battlepass": true, "quests": true, "leaderboards": true, "map": true}'
)


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("map_url", sa.String(length=512), nullable=True))
    op.add_column(
        "game_servers",
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Backfill existing rows with all features enabled, then enforce NOT NULL.
    op.execute(f"UPDATE game_servers SET features = '{_ALL_FEATURES}'::jsonb WHERE features IS NULL")
    op.alter_column(
        "game_servers",
        "features",
        nullable=False,
        server_default=sa.text(f"'{_ALL_FEATURES}'::jsonb"),
    )


def downgrade() -> None:
    op.drop_column("game_servers", "features")
    op.drop_column("game_servers", "map_url")
