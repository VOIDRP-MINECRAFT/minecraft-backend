"""add game_servers.staff_only (server visible only to staff)

Revision ID: 20260824_0001
Revises: 20260821_0001
Create Date: 2026-08-24

Per-server "admin-only" switch: the server stays out of the public catalogue
(/servers → site + launcher) for everyone except full admins and moderators
holding the new ``servers.hidden.view`` permission. Independent of
``is_visible``, which hides the server from absolutely everyone.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260824_0001"
down_revision = "20260821_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_servers",
        sa.Column("staff_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("game_servers", "staff_only", server_default=None)


def downgrade() -> None:
    op.drop_column("game_servers", "staff_only")
