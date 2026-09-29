"""badge roles: a role that carries no permissions — a label about the person

``staff_roles.is_badge``: shown like a role, never grants anything and does not count
for seniority. Additive only.

Revision ID: 20260929_0011
Revises: 20260929_0010
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260929_0011"
down_revision = "20260929_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_roles", sa.Column("is_badge", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("staff_roles", "is_badge")
