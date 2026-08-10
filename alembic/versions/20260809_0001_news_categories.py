"""news categories (update/media): per-category channels + permissions

Revision ID: 20260809_0001
Revises: 20260808_0001
Create Date: 2026-08-09

Splits news into two categories with independent TG/Discord channels and
moderator permissions:
  1. news_posts.category (update|media, default update)
  2. game_servers.news_channels JSONB {category: {telegram:[], discord:[]}}
     backfilled from the old flat telegram_targets/discord_webhooks (→ update),
     then the flat columns are dropped
  3. users.staff_permissions: news.view/news.manage → news.{updates,media}.{view,manage}
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260809_0001"
down_revision = "20260808_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. news_posts.category
    op.add_column(
        "news_posts",
        sa.Column("category", sa.String(length=16), nullable=False, server_default="update"),
    )
    op.create_index(
        "ix_news_posts_server_category_pub",
        "news_posts",
        ["server_id", "category", "is_published", "published_at"],
    )

    # 2. game_servers.news_channels + backfill from flat columns
    op.add_column(
        "game_servers",
        sa.Column("news_channels", JSONB(), nullable=False, server_default="{}"),
    )
    op.execute(
        """
        UPDATE game_servers SET news_channels = jsonb_build_object(
            'update', jsonb_build_object(
                'telegram', COALESCE(telegram_targets, '[]'::jsonb),
                'discord',  COALESCE(discord_webhooks, '[]'::jsonb)
            ),
            'media', jsonb_build_object('telegram', '[]'::jsonb, 'discord', '[]'::jsonb)
        )
        """
    )
    op.drop_column("game_servers", "telegram_targets")
    op.drop_column("game_servers", "discord_webhooks")

    # 3. Remap moderator permissions (JSONB array of strings)
    op.execute(
        """
        UPDATE users SET staff_permissions = (
            SELECT COALESCE(jsonb_agg(DISTINCT p), '[]'::jsonb) FROM (
                SELECT CASE
                    WHEN k = 'news.view'   THEN 'news.updates.view'
                    WHEN k = 'news.manage' THEN 'news.updates.manage'
                    ELSE k END AS p
                FROM jsonb_array_elements_text(staff_permissions) AS k
                UNION
                SELECT CASE
                    WHEN k = 'news.view'   THEN 'news.media.view'
                    WHEN k = 'news.manage' THEN 'news.media.manage'
                    ELSE NULL END AS p
                FROM jsonb_array_elements_text(staff_permissions) AS k
            ) x WHERE p IS NOT NULL
        )
        WHERE is_moderator = true
        """
    )


def downgrade() -> None:
    op.add_column("game_servers", sa.Column("telegram_targets", JSONB(), nullable=False, server_default="[]"))
    op.add_column("game_servers", sa.Column("discord_webhooks", JSONB(), nullable=False, server_default="[]"))
    op.execute(
        """
        UPDATE game_servers SET
            telegram_targets = COALESCE(news_channels->'update'->'telegram', '[]'::jsonb),
            discord_webhooks = COALESCE(news_channels->'update'->'discord', '[]'::jsonb)
        """
    )
    op.drop_column("game_servers", "news_channels")
    op.drop_index("ix_news_posts_server_category_pub", table_name="news_posts")
    op.drop_column("news_posts", "category")
