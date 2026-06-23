"""add_player_market_web_actions

Revision ID: 5ed45978ace6
Revises: 20260604_0001
Create Date: 2026-06-05 20:57:11.030862

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '5ed45978ace6'
down_revision = '20260604_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'player_market_web_actions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('player_name', sa.String(length=16), nullable=False),
        sa.Column('action_type', sa.String(length=32), nullable=False),
        sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_player_market_web_actions')),
    )
    op.create_index('ix_web_actions_player_name', 'player_market_web_actions', ['player_name'])
    op.create_index('ix_web_actions_status', 'player_market_web_actions', ['status'])
    op.create_index('ix_web_actions_player_status', 'player_market_web_actions', ['player_name', 'status'])
    op.create_index('ix_web_actions_created_at', 'player_market_web_actions', ['created_at'])


def downgrade() -> None:
    op.drop_table('player_market_web_actions')
