"""console queue and log lines for servers whose plugin talks to the backend itself

* ``server_commands`` — commands for a server's plugin to run (the console, kicks,
  punishments… without RCON), with their output;
* ``server_log_lines`` — the tail of the server log the plugin ships (the admin's log and
  chat for a partner server, whose files are not on our machine).

Revision ID: 20260930_0009
Revises: 20260930_0008
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260930_0009"
down_revision = "20260930_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_commands",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        # pending → sent → done | failed; expired when nobody took it in time
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_server_commands_server_status", "server_commands", ["server_id", "status"])
    op.create_table(
        "server_log_lines",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_server_log_lines_server_id", "server_log_lines", ["server_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_server_log_lines_server_id", table_name="server_log_lines")
    op.drop_table("server_log_lines")
    op.drop_index("ix_server_commands_server_status", table_name="server_commands")
    op.drop_table("server_commands")
