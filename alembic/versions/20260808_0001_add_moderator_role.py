"""add moderator role (is_moderator + staff_permissions) to users

Revision ID: 20260808_0001
Revises: 20260807_0004
Create Date: 2026-08-08

Adds a restricted staff role: moderators get admin-panel access limited to the
permission keys stored in staff_permissions (see core/permissions.py). Full
admins (is_admin) bypass all permission checks.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260808_0001"
down_revision = "20260807_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_moderator", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("staff_permissions", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("users", "staff_permissions")
    op.drop_column("users", "is_moderator")
