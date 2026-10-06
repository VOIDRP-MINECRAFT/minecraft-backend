"""Login days per player and server (login streaks, funnel days) and launcher download clicks.

Revision ID: 20261006_0005
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261006_0005"
down_revision = "20261006_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_login_days",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
    )
    op.create_index("uq_player_login_days", "player_login_days", ["user_id", "server_id", "day"], unique=True)
    op.create_table(
        "launcher_downloads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_launcher_downloads_created", "launcher_downloads", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_launcher_downloads_created", table_name="launcher_downloads")
    op.drop_table("launcher_downloads")
    op.drop_index("uq_player_login_days", table_name="player_login_days")
    op.drop_table("player_login_days")
