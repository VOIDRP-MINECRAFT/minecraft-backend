"""per-server watchdog: settings + state, and events

New tables only; nothing existing changes.

Revision ID: 20260929_0004
Revises: 20260929_0003
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_0004"
down_revision = "20260929_0003"
branch_labels = None
depends_on = None


def _server_fk():
    return sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True)


def _stamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "server_watchdogs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("server_id", name="uq_server_watchdogs_server"),
    )
    op.create_table(
        "server_watchdog_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("kind", sa.String(16), nullable=False, index=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("dump_path", sa.String(1024), nullable=True),
        *_stamps(),
    )


def downgrade() -> None:
    op.drop_table("server_watchdog_events")
    op.drop_table("server_watchdogs")
