"""create news_posts + per-server news channels (telegram/discord)

Revision ID: 20260807_0002
Revises: 20260807_0001
Create Date: 2026-08-07

Adds ``news_posts`` (server-scoped news, Markdown body, publish + broadcast flags)
and per-server channel config columns on ``game_servers``. The ``news`` feature
flag is handled by JSONB default (absent key ⇒ enabled), so no data backfill.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260807_0002"
down_revision = "20260807_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("telegram_chat_id", sa.String(length=128), nullable=True))
    op.add_column("game_servers", sa.Column("discord_webhook_url", sa.String(length=512), nullable=True))

    op.create_table(
        "news_posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_image_url", sa.String(length=512), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("author_name", sa.String(length=64), nullable=True),
        sa.Column("posted_telegram", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("posted_discord", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_posts")),
    )
    op.create_index(op.f("ix_news_posts_server_id"), "news_posts", ["server_id"])
    op.create_index(op.f("ix_news_posts_is_published"), "news_posts", ["is_published"])
    op.create_index(op.f("ix_news_posts_author_id"), "news_posts", ["author_id"])
    op.create_index(
        "ix_news_posts_server_published",
        "news_posts",
        ["server_id", "is_published", "published_at"],
    )


def downgrade() -> None:
    op.drop_table("news_posts")
    op.drop_column("game_servers", "discord_webhook_url")
    op.drop_column("game_servers", "telegram_chat_id")
