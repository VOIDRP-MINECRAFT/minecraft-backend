"""Second-day return: per-server settings, reward/welcome deliveries, Telegram reminders.

Revision ID: 20261006_0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261006_0004"
down_revision = "20261006_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("retention_settings", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.create_table(
        "retention_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("nickname", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),  # welcome | day2 | test
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),  # pending | delivered | failed
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_retention_deliveries_due", "retention_deliveries", ["status", "deliver_after"])
    op.create_index("ix_retention_deliveries_server_created", "retention_deliveries", ["server_id", "created_at"])
    # One welcome and one second-day reward per player and server, ever (tests are not limited).
    op.create_index("uq_retention_deliveries_once", "retention_deliveries", ["server_id", "user_id", "kind"], unique=True,
                    postgresql_where=sa.text("kind IN ('welcome', 'day2') AND user_id IS NOT NULL"))
    op.create_table(
        "player_reminders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),  # day2 | optout
        sa.Column("sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_player_reminders_user_kind", "player_reminders", ["user_id", "kind"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_player_reminders_user_kind", table_name="player_reminders")
    op.drop_table("player_reminders")
    op.drop_index("uq_retention_deliveries_once", table_name="retention_deliveries")
    op.drop_index("ix_retention_deliveries_server_created", table_name="retention_deliveries")
    op.drop_index("ix_retention_deliveries_due", table_name="retention_deliveries")
    op.drop_table("retention_deliveries")
    op.drop_column("game_servers", "retention_settings")
