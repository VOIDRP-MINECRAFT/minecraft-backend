"""add kill-streak stats + bounty source (notoriety/wanted system)

Revision ID: 20260713_0003
Revises: 20260713_0002
Create Date: 2026-07-13

Adds current/best kill-streak columns to player_stat_cache (fed as absolute values
by the abyss mod's notoriety tracker) and a ``source`` discriminator on bounties so
server-funded "wanted" bounties can be told apart from player-placed ones.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0003"
down_revision = "20260713_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player_stat_cache",
        sa.Column("current_kill_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "player_stat_cache",
        sa.Column("best_kill_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "bounties",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="player"),
    )


def downgrade() -> None:
    op.drop_column("bounties", "source")
    op.drop_column("player_stat_cache", "best_kill_streak")
    op.drop_column("player_stat_cache", "current_kill_streak")
