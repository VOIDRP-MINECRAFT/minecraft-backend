"""add game_servers.telegram_thread_id (forum topic per server)

Revision ID: 20260807_0003
Revises: 20260807_0002
Create Date: 2026-08-07

One Telegram supergroup with forum topics — each server posts news to its own
topic via message_thread_id. Null → root chat.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260807_0003"
down_revision = "20260807_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("telegram_thread_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("game_servers", "telegram_thread_id")
