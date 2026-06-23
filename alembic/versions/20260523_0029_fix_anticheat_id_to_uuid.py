"""fix anticheat_violations and anticheat_mod_snapshots id column to UUID type

Revision ID: 20260523_0029
Revises: 20260523_0028
Create Date: 2026-05-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260523_0029"
down_revision = "20260523_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE anticheat_violations ALTER COLUMN id TYPE UUID USING id::uuid"
    )
    op.execute(
        "ALTER TABLE anticheat_mod_snapshots ALTER COLUMN id TYPE UUID USING id::uuid"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE anticheat_mod_snapshots ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
    )
    op.execute(
        "ALTER TABLE anticheat_violations ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
    )
