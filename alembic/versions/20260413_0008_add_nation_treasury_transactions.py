"""add nation treasury transactions

Revision ID: 20260413_0008
Revises: 20260413_0007
Create Date: 2026-04-13 22:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0008"
down_revision = "20260413_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nation_treasury_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=True),
        sa.Column("counterparty_nation_id", sa.Uuid(), nullable=True),
        sa.Column("alliance_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("fee_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["counterparty_nation_id"], ["nations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["alliance_id"], ["alliances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nation_treasury_transactions_nation_id", "nation_treasury_transactions", ["nation_id"], unique=False)
    op.create_index("ix_nation_treasury_transactions_alliance_id", "nation_treasury_transactions", ["alliance_id"], unique=False)
    op.create_index("ix_nation_treasury_transactions_created_at", "nation_treasury_transactions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_nation_treasury_transactions_created_at", table_name="nation_treasury_transactions")
    op.drop_index("ix_nation_treasury_transactions_alliance_id", table_name="nation_treasury_transactions")
    op.drop_index("ix_nation_treasury_transactions_nation_id", table_name="nation_treasury_transactions")
    op.drop_table("nation_treasury_transactions")