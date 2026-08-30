"""add void_coins premium currency to player_accounts

Revision ID: 20260830_0003
Revises: 20260830_0002
Create Date: 2026-08-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260830_0003"
down_revision = "20260830_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player_accounts",
        sa.Column("void_coins", sa.BigInteger(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("player_accounts", "void_coins")
