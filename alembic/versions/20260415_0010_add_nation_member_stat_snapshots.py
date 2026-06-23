"""add nation member stat snapshots

Revision ID: 20260415_0010
Revises: 20260414_0009
Create Date: 2026-04-15 12:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_0010"
down_revision = "20260414_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nation_member_stat_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("minecraft_nickname", sa.String(length=16), nullable=False),
        sa.Column("minecraft_nickname_normalized", sa.String(length=16), nullable=False),
        sa.Column("total_playtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pvp_kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mob_kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deaths", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_placed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("blocks_broken", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="cached"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "nation_id",
            "minecraft_nickname_normalized",
            name="uq_nation_member_stat_snapshots_nation_nickname",
        ),
    )
    op.create_index(
        "ix_nation_member_stat_snapshots_nation_id",
        "nation_member_stat_snapshots",
        ["nation_id"],
        unique=False,
    )
    op.create_index(
        "ix_nation_member_stat_snapshots_user_id",
        "nation_member_stat_snapshots",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_nation_member_stat_snapshots_last_synced_at",
        "nation_member_stat_snapshots",
        ["last_synced_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_nation_member_stat_snapshots_last_synced_at", table_name="nation_member_stat_snapshots")
    op.drop_index("ix_nation_member_stat_snapshots_user_id", table_name="nation_member_stat_snapshots")
    op.drop_index("ix_nation_member_stat_snapshots_nation_id", table_name="nation_member_stat_snapshots")
    op.drop_table("nation_member_stat_snapshots")
