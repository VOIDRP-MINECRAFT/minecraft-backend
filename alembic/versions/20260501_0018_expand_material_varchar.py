"""expand material varchar to 192 for enchanted book keys

Revision ID: 20260501_0018
Revises: 20260501_0017
Create Date: 2026-05-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '20260501_0018'
down_revision = '20260501_0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('economy_market_items', 'material',
                    existing_type=sa.String(96), type_=sa.String(192), nullable=False)
    op.alter_column('economy_shop_transactions', 'material',
                    existing_type=sa.String(96), type_=sa.String(192), nullable=False)


def downgrade() -> None:
    op.alter_column('economy_shop_transactions', 'material',
                    existing_type=sa.String(192), type_=sa.String(96), nullable=False)
    op.alter_column('economy_market_items', 'material',
                    existing_type=sa.String(192), type_=sa.String(96), nullable=False)
