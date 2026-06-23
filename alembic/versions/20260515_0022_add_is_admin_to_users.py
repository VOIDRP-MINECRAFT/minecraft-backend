"""add is_admin to users

Revision ID: 20260515_0022
Revises: 20260514_0021
Create Date: 2026-05-15

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260515_0022"
down_revision = "20260514_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
