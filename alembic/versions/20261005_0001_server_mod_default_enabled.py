"""optional mods: enabled by default or not

``server_mod_meta.default_enabled`` — for an optional (not locked) client mod, whether the
launcher installs it for a player who has not chosen yet. True keeps today's behaviour.

Revision ID: 20261005_0001
Revises: 20260930_0009
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_0001"
down_revision = "20260930_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_mod_meta",
        sa.Column("default_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("server_mod_meta", "default_enabled")
