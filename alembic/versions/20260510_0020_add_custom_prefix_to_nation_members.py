"""add custom_prefix to nation_members

Revision ID: 20260510_0020
Revises: 20260502_0019
Create Date: 2026-05-10

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '20260510_0020'
down_revision = '20260502_0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('nation_members', sa.Column('custom_prefix', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('nation_members', 'custom_prefix')
