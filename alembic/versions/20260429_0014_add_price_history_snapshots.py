"""add price history snapshots

Revision ID: 20260429_0014
Revises: 20260426_0013
Create Date: 2026-04-29 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_0014"
down_revision = "20260426_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_history_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("material", sa.String(96), nullable=False),
        sa.Column("buy_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("sell_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("buy_multiplier", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("sell_multiplier", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_price_history_snapshots"),
    )
    op.create_index("ix_price_history_snapshots_material", "price_history_snapshots", ["material"])
    op.create_index("ix_price_history_snapshots_recorded_at", "price_history_snapshots", ["recorded_at"])
    op.create_index(
        "ix_price_history_snapshots_material_recorded_at",
        "price_history_snapshots",
        ["material", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_history_snapshots_material_recorded_at", table_name="price_history_snapshots")
    op.drop_index("ix_price_history_snapshots_recorded_at", table_name="price_history_snapshots")
    op.drop_index("ix_price_history_snapshots_material", table_name="price_history_snapshots")
    op.drop_table("price_history_snapshots")
