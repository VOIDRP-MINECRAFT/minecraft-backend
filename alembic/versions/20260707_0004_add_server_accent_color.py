"""add per-server theme accent color

Revision ID: 20260707_0004
Revises: 20260707_0003
Create Date: 2026-07-07

Adds ``accent_color`` (hex string) to ``game_servers``. The site/launcher tint
their UI with it when the server is selected; null keeps the default violet.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260707_0004"
down_revision = "20260707_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("accent_color", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("game_servers", "accent_color")
