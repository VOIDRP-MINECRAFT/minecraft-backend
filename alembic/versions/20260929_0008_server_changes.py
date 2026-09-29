"""mods & plugins: queued jar changes and restart-to-apply jobs

New tables only; nothing existing changes.

Revision ID: 20260929_0008
Revises: 20260929_0007
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260929_0008"
down_revision = "20260929_0007"
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
        "server_file_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=True),
        sa.Column("replaces", sa.String(255), nullable=True),
        sa.Column("label", sa.String(256), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
    )
    op.create_table(
        "server_restart_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("step", sa.String(256), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("warn_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("requested_by", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
    )


def downgrade() -> None:
    op.drop_table("server_restart_jobs")
    op.drop_table("server_file_changes")
