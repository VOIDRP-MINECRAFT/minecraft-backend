"""create player_weekly_challenges table

Revision ID: 20260830_0001
Revises: 20260829_0002
Create Date: 2026-08-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260830_0001"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_weekly_challenges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(48), nullable=False),
        sa.Column("minecraft_nickname_normalized", sa.String(48), nullable=False),
        sa.Column("week_id", sa.String(16), nullable=False),
        sa.Column("challenges", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name="fk_player_weekly_challenges_server_id_game_servers", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id", "minecraft_nickname_normalized",
            name="uq_weekly_challenges_server_nick",
        ),
    )
    op.create_index(
        "ix_player_weekly_challenges_minecraft_nickname_normalized",
        "player_weekly_challenges", ["minecraft_nickname_normalized"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_weekly_challenges_minecraft_nickname_normalized",
        table_name="player_weekly_challenges",
    )
    op.drop_table("player_weekly_challenges")
