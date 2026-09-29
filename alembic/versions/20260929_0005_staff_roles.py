"""staff roles: an owner, and who made someone staff and when

- ``users.is_owner``: the one person who appoints and removes full admins. Set for the
  existing admin ``mironoouv``.
- ``users.staff_since`` / ``users.staff_granted_by``: when someone became staff, by whom.

Revision ID: 20260929_0005
Revises: 20260929_0004
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260929_0005"
down_revision = "20260929_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("staff_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("staff_granted_by", sa.String(64), nullable=True))
    op.execute("UPDATE users SET is_owner = true WHERE site_login = 'mironoouv' AND is_admin")


def downgrade() -> None:
    op.drop_column("users", "staff_granted_by")
    op.drop_column("users", "staff_since")
    op.drop_column("users", "is_owner")
