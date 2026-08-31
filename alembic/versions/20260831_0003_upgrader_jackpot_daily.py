"""upgrader jackpot + daily free spin (tables) and jackpot/daily settings columns

Revision ID: 20260831_0003
Revises: 20260831_0002
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260831_0003"
down_revision = "20260831_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── settings: jackpot + daily tunables (defaults so the existing row is valid) ──
    op.add_column("void_upgrader_settings", sa.Column("jackpot_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("void_upgrader_settings", sa.Column("jackpot_rate", sa.Float(), server_default="0.01", nullable=False))
    op.add_column("void_upgrader_settings", sa.Column("jackpot_chance", sa.Float(), server_default="0.001", nullable=False))
    op.add_column("void_upgrader_settings", sa.Column("jackpot_seed", sa.BigInteger(), server_default="500", nullable=False))
    op.add_column("void_upgrader_settings", sa.Column("daily_free_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("void_upgrader_settings", sa.Column("daily_free_stake", sa.Integer(), server_default="25", nullable=False))

    # ── server-wide jackpot ──
    op.create_table(
        "void_upgrader_jackpot",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_winner_nickname", sa.String(length=48), nullable=True),
        sa.Column("last_amount", sa.BigInteger(), nullable=True),
        sa.Column("last_won_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_jackpot_server", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", name="uq_void_upgrader_jackpot_server"),
    )

    # ── daily free-spin ledger ──
    op.create_table(
        "void_upgrader_daily",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(length=48), nullable=False),
        sa.Column("last_free_spin_date", sa.Date(), nullable=False),
        sa.Column("streak", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_daily_server", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_void_upgrader_daily_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "user_id", name="uq_void_upgrader_daily_server_user"),
    )
    op.create_index("ix_void_upgrader_daily_user", "void_upgrader_daily", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_void_upgrader_daily_user", table_name="void_upgrader_daily")
    op.drop_table("void_upgrader_daily")
    op.drop_table("void_upgrader_jackpot")
    for col in ("daily_free_stake", "daily_free_enabled", "jackpot_seed", "jackpot_chance", "jackpot_rate", "jackpot_enabled"):
        op.drop_column("void_upgrader_settings", col)
