"""add news_posts.posted_telegram_at / posted_discord_at

Revision ID: 20260824_0002
Revises: 20260824_0001
Create Date: 2026-08-24

The boolean `posted_*` flags only say "was ever delivered". The admin news panel
now warns before re-sending a post into a channel, which needs the time of the
last successful delivery. Backfilled from `published_at` for posts already
marked as delivered so existing rows show a plausible time instead of "никогда".
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260824_0002"
down_revision = "20260824_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_posts",
        sa.Column("posted_telegram_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "news_posts",
        sa.Column("posted_discord_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE news_posts SET posted_telegram_at = published_at "
        "WHERE posted_telegram IS TRUE AND published_at IS NOT NULL"
    )
    op.execute(
        "UPDATE news_posts SET posted_discord_at = published_at "
        "WHERE posted_discord IS TRUE AND published_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("news_posts", "posted_discord_at")
    op.drop_column("news_posts", "posted_telegram_at")
