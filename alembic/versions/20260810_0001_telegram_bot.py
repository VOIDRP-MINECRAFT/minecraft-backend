"""telegram bot: account link + game chats + scores

Revision ID: 20260810_0001
Revises: 20260809_0001
Create Date: 2026-08-10

Supports the aiogram Telegram bot:
  1. users.telegram_user_id (BigInt, unique) + telegram_username
  2. telegram_link_tokens  — one-time account-link nonces (bot → site)
  3. telegram_game_chats   — chats/topics where mini-games are allowed
  4. telegram_game_scores  — per-chat mini-game points
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260810_0001"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_user_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("telegram_username", sa.String(length=64), nullable=True))
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True)

    op.create_table(
        "telegram_link_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_link_tokens"),
    )
    op.create_index("ix_telegram_link_tokens_token", "telegram_link_tokens", ["token"], unique=True)

    op.create_table(
        "telegram_game_chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["added_by_user_id"], ["users.id"],
            name="fk_telegram_game_chats_added_by_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_game_chats"),
        sa.UniqueConstraint("chat_id", "thread_id", name="uq_telegram_game_chats_chat_thread"),
    )
    op.create_index("ix_telegram_game_chats_chat_id", "telegram_game_chats", ["chat_id"])

    op.create_table(
        "telegram_game_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_daily_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_game_scores"),
        sa.UniqueConstraint("telegram_user_id", "chat_id", name="uq_telegram_game_scores_user_chat"),
    )
    op.create_index("ix_telegram_game_scores_telegram_user_id", "telegram_game_scores", ["telegram_user_id"])
    op.create_index("ix_telegram_game_scores_chat_id", "telegram_game_scores", ["chat_id"])


def downgrade() -> None:
    op.drop_table("telegram_game_scores")
    op.drop_table("telegram_game_chats")
    op.drop_index("ix_telegram_link_tokens_token", table_name="telegram_link_tokens")
    op.drop_table("telegram_link_tokens")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_user_id")
