"""file manager: history of every file saved through the admin panel

New table only; nothing existing changes.

Revision ID: 20260929_0007
Revises: 20260929_0006
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260929_0007"
down_revision = "20260929_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("path", sa.String(1024), nullable=False, index=True),
        sa.Column("content_before", sa.Text(), nullable=True),
        sa.Column("content_after", sa.Text(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lines_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("author", sa.String(64), nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("file_revisions")
