"""add nation capital coords

Revision ID: 20260502_0019
Revises: 20260501_0018
Create Date: 2026-05-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '20260502_0019'
down_revision = '20260501_0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('nations', sa.Column('capital_x', sa.Integer(), nullable=True))
    op.add_column('nations', sa.Column('capital_z', sa.Integer(), nullable=True))
    op.add_column('nations', sa.Column('capital_world', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('nations', 'capital_world')
    op.drop_column('nations', 'capital_z')
    op.drop_column('nations', 'capital_x')
