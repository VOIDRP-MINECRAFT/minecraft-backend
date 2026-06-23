"""add player_stat_cache table

Revision ID: 20260501_0017
Revises: 20260501_0016
Create Date: 2026-05-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '20260501_0017'
down_revision = '20260501_0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'player_stat_cache',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('minecraft_nickname', sa.String(16), nullable=False),
        sa.Column('minecraft_nickname_normalized', sa.String(16), nullable=False),
        sa.Column('total_playtime_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pvp_kills', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mob_kills', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deaths', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('blocks_placed', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('blocks_broken', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('current_balance', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('completed_quests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source', sa.String(32), nullable=False, server_default='live'),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('minecraft_nickname_normalized', name='uq_player_stat_cache_nickname_normalized'),
    )
    op.create_index('ix_player_stat_cache_user_id', 'player_stat_cache', ['user_id'])
    op.create_index('ix_player_stat_cache_minecraft_nickname_normalized', 'player_stat_cache', ['minecraft_nickname_normalized'])
    op.create_index('ix_player_stat_cache_last_synced_at', 'player_stat_cache', ['last_synced_at'])


def downgrade() -> None:
    op.drop_table('player_stat_cache')
