"""add completed_quests to nation_member_stat_snapshots

Revision ID: 20260501_0016
Revises: 20260430_0015
Create Date: 2026-05-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '20260501_0016'
down_revision = '20260430_0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'nation_member_stat_snapshots',
        sa.Column('completed_quests', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('nation_member_stat_snapshots', 'completed_quests')
