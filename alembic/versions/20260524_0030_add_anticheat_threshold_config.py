"""add anticheat_threshold_configs table

Revision ID: 20260524_0030
Revises: 20260523_0029
Create Date: 2026-05-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260524_0030"
down_revision = "20260523_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anticheat_threshold_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("min_value", sa.Float, nullable=False, server_default="0"),
        sa.Column("max_value", sa.Float, nullable=False, server_default="100"),
        sa.Column("step", sa.Float, nullable=False, server_default="0.1"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("key", name="uq_anticheat_threshold_configs_key"),
    )
    op.create_index("ix_anticheat_threshold_configs_key", "anticheat_threshold_configs", ["key"])


def downgrade() -> None:
    op.drop_index("ix_anticheat_threshold_configs_key", "anticheat_threshold_configs")
    op.drop_table("anticheat_threshold_configs")
