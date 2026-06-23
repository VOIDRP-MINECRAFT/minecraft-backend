"""add landing_screenshots

Revision ID: 20260523_0028
Revises: 20260523_0027
Create Date: 2026-05-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260523_0028"
down_revision = "20260523_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "landing_screenshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_landing_screenshots"),
    )


def downgrade() -> None:
    op.drop_table("landing_screenshots")
