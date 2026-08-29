"""create player_playtime_daily table (in-game activity chart)

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260829_0002"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_playtime_daily",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(48), nullable=False),
        sa.Column("minecraft_nickname_normalized", sa.String(48), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("seconds", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name="fk_player_playtime_daily_server_id_game_servers", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id", "minecraft_nickname_normalized", "day",
            name="uq_playtime_daily_server_nick_day",
        ),
    )
    op.create_index(
        "ix_player_playtime_daily_minecraft_nickname_normalized",
        "player_playtime_daily", ["minecraft_nickname_normalized"],
    )
    op.create_index("ix_player_playtime_daily_day", "player_playtime_daily", ["day"])


def downgrade() -> None:
    op.drop_index("ix_player_playtime_daily_day", table_name="player_playtime_daily")
    op.drop_index(
        "ix_player_playtime_daily_minecraft_nickname_normalized",
        table_name="player_playtime_daily",
    )
    op.drop_table("player_playtime_daily")
