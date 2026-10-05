"""server_integration_events (connection history) and a grace period for a rotated secret

* ``server_integration_events`` — what happened to a server's VoidRP plugins: a module came up
  or went off, a plugin changed version or appeared, a required module went quiet and came back.
* ``game_servers.previous_game_auth_secret`` / ``previous_secret_until`` — after a smooth
  rotation the old secret keeps working until then, and VoidRpPerms moves the plugins over.

Revision ID: 20261005_0006
Revises: 20261005_0005
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_0006"
down_revision = "20261005_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_integration_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("plugin", sa.String(64), nullable=True),
        sa.Column("detail", sa.String(300), nullable=True),
    )
    op.create_index("ix_server_integration_events_server_at", "server_integration_events", ["server_id", "at"])
    op.add_column("game_servers", sa.Column("previous_game_auth_secret", sa.String(255), nullable=True))
    op.add_column("game_servers", sa.Column("previous_secret_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("game_servers", "previous_secret_until")
    op.drop_column("game_servers", "previous_game_auth_secret")
    op.drop_index("ix_server_integration_events_server_at", table_name="server_integration_events")
    op.drop_table("server_integration_events")
