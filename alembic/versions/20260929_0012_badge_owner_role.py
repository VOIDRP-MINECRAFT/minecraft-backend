"""badges can belong to a role: its members hand the badge out and edit it

``staff_roles.owner_role_id`` (nullable, only meaningful for badges) → the role whose
members own the badge. Additive only.

Revision ID: 20260929_0012
Revises: 20260929_0011
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260929_0012"
down_revision = "20260929_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_roles", sa.Column("owner_role_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_staff_roles_owner_role_id_staff_roles", "staff_roles", "staff_roles",
                          ["owner_role_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_staff_roles_owner_role_id_staff_roles", "staff_roles", type_="foreignkey")
    op.drop_column("staff_roles", "owner_role_id")
