"""create player_game_settings table

Revision ID: 20260830_0002
Revises: 20260830_0001
Create Date: 2026-08-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260830_0002"
down_revision = "20260830_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_game_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name="fk_player_game_settings_server_id_game_servers", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_player_game_settings_user_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "user_id", name="uq_player_game_settings_server_user"),
    )
    op.create_index("ix_player_game_settings_user_id", "player_game_settings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_player_game_settings_user_id", table_name="player_game_settings")
    op.drop_table("player_game_settings")
