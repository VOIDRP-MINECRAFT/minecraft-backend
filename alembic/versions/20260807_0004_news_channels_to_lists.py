"""switch per-server news channels to lists (multiple TG targets + Discord webhooks)

Revision ID: 20260807_0004
Revises: 20260807_0003
Create Date: 2026-08-07

Replaces the single telegram_chat_id / telegram_thread_id / discord_webhook_url
columns with JSONB lists so a server can post news to several destinations
(multiple TG topics/channels and multiple Discord webhooks).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260807_0004"
down_revision = "20260807_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_servers",
        sa.Column("telegram_targets", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "game_servers",
        sa.Column("discord_webhooks", JSONB(), nullable=False, server_default="[]"),
    )
    # Backfill from the old single columns where present.
    op.execute(
        """
        UPDATE game_servers
        SET telegram_targets = jsonb_build_array(
            jsonb_build_object(
                'chat_id', telegram_chat_id,
                'thread_id', telegram_thread_id
            )
        )
        WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id <> ''
        """
    )
    op.execute(
        """
        UPDATE game_servers
        SET discord_webhooks = jsonb_build_array(discord_webhook_url)
        WHERE discord_webhook_url IS NOT NULL AND discord_webhook_url <> ''
        """
    )
    op.drop_column("game_servers", "telegram_chat_id")
    op.drop_column("game_servers", "telegram_thread_id")
    op.drop_column("game_servers", "discord_webhook_url")


def downgrade() -> None:
    op.add_column("game_servers", sa.Column("telegram_chat_id", sa.String(length=128), nullable=True))
    op.add_column("game_servers", sa.Column("telegram_thread_id", sa.Integer(), nullable=True))
    op.add_column("game_servers", sa.Column("discord_webhook_url", sa.String(length=512), nullable=True))
    op.drop_column("game_servers", "telegram_targets")
    op.drop_column("game_servers", "discord_webhooks")
