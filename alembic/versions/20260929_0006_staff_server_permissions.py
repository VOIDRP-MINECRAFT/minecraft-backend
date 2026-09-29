"""per-server staff permissions: users.staff_server_permissions

``{"<game_servers.id>": [permission keys]}`` on top of ``staff_permissions``. Existing
grants stay in ``staff_permissions`` and keep meaning "on every server", so no
moderator loses anything.

Revision ID: 20260929_0006
Revises: 20260929_0005
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_0006"
down_revision = "20260929_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("staff_server_permissions", postgresql.JSONB(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("users", "staff_server_permissions")
