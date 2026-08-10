"""create tiktok campaigns + click rewards (announce videos, reward clicks)

Revision ID: 20260807_0001
Revises: 20260805_0001
Create Date: 2026-08-07

Adds ``tiktok_campaigns`` (one row per published video announced via
``/vrgs tiktok <url>``) and ``tiktok_click_rewards`` (one-time random reward per
player who opens the tracked link). Both server-scoped.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260807_0001"
down_revision = "20260805_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tiktok_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("video_url", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tiktok_campaigns")),
    )
    op.create_index(op.f("ix_tiktok_campaigns_server_id"), "tiktok_campaigns", ["server_id"])

    op.create_table(
        "tiktok_click_rewards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("minecraft_uuid", sa.String(length=64), nullable=False),
        sa.Column("minecraft_nickname", sa.String(length=32), nullable=True),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["tiktok_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tiktok_click_rewards")),
        sa.UniqueConstraint("campaign_id", "minecraft_uuid", name="uq_tiktok_reward_campaign_uuid"),
    )
    op.create_index(op.f("ix_tiktok_click_rewards_server_id"), "tiktok_click_rewards", ["server_id"])
    op.create_index(op.f("ix_tiktok_click_rewards_campaign_id"), "tiktok_click_rewards", ["campaign_id"])
    op.create_index(op.f("ix_tiktok_click_rewards_minecraft_uuid"), "tiktok_click_rewards", ["minecraft_uuid"])


def downgrade() -> None:
    op.drop_table("tiktok_click_rewards")
    op.drop_table("tiktok_campaigns")
