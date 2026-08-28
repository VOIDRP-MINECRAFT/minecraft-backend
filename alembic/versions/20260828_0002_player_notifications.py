"""create player_notifications table (reactive in-game notifications)

Revision ID: 20260828_0002
Revises: 20260828_0001
Create Date: 2026-08-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_0002"
down_revision = "20260828_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(400), nullable=True),
        sa.Column("icon", sa.String(48), nullable=True),
        sa.Column("accent", sa.String(16), nullable=True),
        sa.Column("action_type", sa.String(24), nullable=True),
        sa.Column("action_payload", sa.String(200), nullable=True),
        sa.Column("action_label", sa.String(48), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name="fk_player_notifications_server_id_game_servers", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_player_notifications_user_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_notifications"),
    )
    op.create_index("ix_player_notifications_server_id", "player_notifications", ["server_id"])
    op.create_index("ix_player_notifications_user_id", "player_notifications", ["user_id"])
    # Fast "undismissed for this user on this server, newest first" lookups.
    op.create_index(
        "ix_player_notifications_feed",
        "player_notifications",
        ["server_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_player_notifications_feed", table_name="player_notifications")
    op.drop_index("ix_player_notifications_user_id", table_name="player_notifications")
    op.drop_index("ix_player_notifications_server_id", table_name="player_notifications")
    op.drop_table("player_notifications")
