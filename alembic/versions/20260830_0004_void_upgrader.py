"""create void upgrader tables

Revision ID: 20260830_0004
Revises: 20260830_0003
Create Date: 2026-08-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260830_0004"
down_revision = "20260830_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "void_upgrader_rewards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("item_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("image_url", sa.String(length=256), nullable=True),
        sa.Column("vc_value", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tier", sa.String(length=24), server_default="common", nullable=False),
        sa.Column("give_command", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_rewards_server", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "item_key", name="uq_void_upgrader_rewards_server_item"),
    )
    op.create_index("ix_void_upgrader_rewards_server_enabled", "void_upgrader_rewards", ["server_id", "enabled"])

    op.create_table(
        "void_upgrader_spins",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(length=48), nullable=False),
        sa.Column("stake", sa.BigInteger(), nullable=False),
        sa.Column("reward_item_key", sa.String(length=128), nullable=False),
        sa.Column("reward_display", sa.String(length=128), nullable=False),
        sa.Column("reward_vc_value", sa.BigInteger(), nullable=False),
        sa.Column("multiplier", sa.Float(), nullable=False),
        sa.Column("win_chance", sa.Float(), nullable=False),
        sa.Column("roll", sa.Float(), nullable=False),
        sa.Column("won", sa.Boolean(), nullable=False),
        sa.Column("server_seed", sa.String(length=64), nullable=False),
        sa.Column("client_seed", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_spins_server", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_void_upgrader_spins_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_void_upgrader_spins_user", "void_upgrader_spins", ["user_id"])
    op.create_index("ix_void_upgrader_spins_server_created", "void_upgrader_spins", ["server_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_void_upgrader_spins_server_created", table_name="void_upgrader_spins")
    op.drop_index("ix_void_upgrader_spins_user", table_name="void_upgrader_spins")
    op.drop_table("void_upgrader_spins")
    op.drop_index("ix_void_upgrader_rewards_server_enabled", table_name="void_upgrader_rewards")
    op.drop_table("void_upgrader_rewards")
