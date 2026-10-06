"""Where a player came from (signup source) and monitoring votes.

Revision ID: 20261006_0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261006_0006"
down_revision = "20261006_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("signup_source", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("signup_landing", sa.String(200), nullable=True))
    op.create_index("ix_users_signup_source", "users", ["signup_source"])
    op.create_table(
        "monitoring_votes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("nickname", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vote_day", sa.Date(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("rewarded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # One vote per player, monitoring and day counts (monitorings re-send on timeouts).
    op.create_index("uq_monitoring_votes_day", "monitoring_votes", ["server_id", "provider", "nickname", "vote_day"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_monitoring_votes_day", table_name="monitoring_votes")
    op.drop_table("monitoring_votes")
    op.drop_index("ix_users_signup_source", table_name="users")
    op.drop_column("users", "signup_landing")
    op.drop_column("users", "signup_source")
