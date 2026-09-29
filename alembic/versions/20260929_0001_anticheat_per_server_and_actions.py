"""anticheat: thresholds per server + a queue of actions for the game server

- ``anticheat_threshold_configs.server_id`` (nullable). The rows there now have no
  server: they stay the value every server gets, and a row with a server overrides one
  key for that server alone. The single unique on ``key`` becomes two partial ones.
- ``anticheat_actions``: what staff ask a game server to do (a CoreProtect rollback and
  its undo), picked up by that server's plugin, with its status and result.

Revision ID: 20260929_0001
Revises: 20260918_0002
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_0001"
down_revision = "20260918_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "anticheat_threshold_configs",
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_anticheat_threshold_configs_server_id", "anticheat_threshold_configs", ["server_id"])
    op.drop_constraint("uq_anticheat_threshold_configs_key", "anticheat_threshold_configs", type_="unique")
    op.create_index(
        "uq_anticheat_threshold_configs_key_global", "anticheat_threshold_configs", ["key"],
        unique=True, postgresql_where=sa.text("server_id IS NULL"),
    )
    op.create_index(
        "uq_anticheat_threshold_configs_key_server", "anticheat_threshold_configs", ["key", "server_id"],
        unique=True, postgresql_where=sa.text("server_id IS NOT NULL"),
    )

    op.create_table(
        "anticheat_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("target_uuid", sa.String(36), nullable=True, index=True),
        sa.Column("target_nick", sa.String(64), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("anticheat_actions")
    op.execute("DELETE FROM anticheat_threshold_configs WHERE server_id IS NOT NULL")
    op.drop_index("uq_anticheat_threshold_configs_key_server", table_name="anticheat_threshold_configs")
    op.drop_index("uq_anticheat_threshold_configs_key_global", table_name="anticheat_threshold_configs")
    op.create_unique_constraint("uq_anticheat_threshold_configs_key", "anticheat_threshold_configs", ["key"])
    op.drop_index("ix_anticheat_threshold_configs_server_id", table_name="anticheat_threshold_configs")
    op.drop_column("anticheat_threshold_configs", "server_id")
