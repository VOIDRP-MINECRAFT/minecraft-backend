"""add nation stats mvp

Revision ID: 20260412_0005
Revises: 20260410_0004
Create Date: 2026-04-12 14:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260412_0005"
down_revision = "20260410_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nation_stats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("treasury_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("territory_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_playtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pvp_kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mob_kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boss_kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deaths", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_placed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("blocks_broken", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("events_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prestige_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nation_id", name="uq_nation_stats_nation_id"),
    )
    op.create_index("ix_nation_stats_nation_id", "nation_stats", ["nation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_nation_stats_nation_id", table_name="nation_stats")
    op.drop_table("nation_stats")
