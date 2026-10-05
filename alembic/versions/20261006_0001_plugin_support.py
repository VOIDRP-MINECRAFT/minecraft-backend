"""plugin_support: the oldest supported version of each of our plugins

Revision ID: 20261006_0001
Revises: 20261005_0006
Create Date: 2026-10-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261006_0001"
down_revision = "20261005_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_support",
        sa.Column("plugin", sa.String(64), primary_key=True),
        sa.Column("min_version", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("plugin_support")
