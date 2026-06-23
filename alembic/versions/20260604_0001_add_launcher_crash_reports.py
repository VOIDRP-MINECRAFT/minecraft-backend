"""add_launcher_crash_reports

Revision ID: 20260604_0001
Revises: 20260603_0034
Create Date: 2026-06-04

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '20260604_0001'
down_revision = '20260603_0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'launcher_crash_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('player_nickname', sa.String(16), nullable=False),
        sa.Column('exit_code', sa.Integer(), nullable=False),
        sa.Column('crash_report', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_launcher_crash_reports'),
    )
    op.create_index('ix_launcher_crash_reports_player_nickname', 'launcher_crash_reports', ['player_nickname'])
    op.create_index('ix_launcher_crash_reports_created_at', 'launcher_crash_reports', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_launcher_crash_reports_created_at', 'launcher_crash_reports')
    op.drop_index('ix_launcher_crash_reports_player_nickname', 'launcher_crash_reports')
    op.drop_table('launcher_crash_reports')
