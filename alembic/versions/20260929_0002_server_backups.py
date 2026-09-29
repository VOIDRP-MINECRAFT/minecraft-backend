"""server backups: archives, restores and the schedule, per server

New tables only; nothing existing changes.

Revision ID: 20260929_0002
Revises: 20260929_0001
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_0002"
down_revision = "20260929_0001"
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
        "server_backups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("kind", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("path", sa.String(1024), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("worlds", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("progress", sa.String(256), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
    )
    op.create_table(
        "server_backup_restores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("backup_id", sa.Uuid(), sa.ForeignKey("server_backups.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("step", sa.String(256), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pre_backup_id", sa.Uuid(), sa.ForeignKey("server_backups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("warn_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("requested_by", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
    )
    op.create_table(
        "server_backup_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("server_id", name="uq_server_backup_settings_server"),
    )


def downgrade() -> None:
    op.drop_table("server_backup_settings")
    op.drop_table("server_backup_restores")
    op.drop_table("server_backups")
