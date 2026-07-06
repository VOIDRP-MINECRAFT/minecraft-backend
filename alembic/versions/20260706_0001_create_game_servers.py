"""create_game_servers

Revision ID: 20260706_0001
Revises: 5ed45978ace6
Create Date: 2026-07-06

"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = '20260706_0001'
down_revision = '5ed45978ace6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'game_servers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon_url', sa.String(length=512), nullable=True),
        sa.Column('banner_url', sa.String(length=512), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_visible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default='25565'),
        sa.Column('mc_version', sa.String(length=32), nullable=False, server_default='1.21.1'),
        sa.Column('loader', sa.String(length=32), nullable=False, server_default='neoforge'),
        sa.Column('java_version', sa.Integer(), nullable=False, server_default='21'),
        sa.Column('neoforge_version', sa.String(length=64), nullable=True),
        sa.Column('pack_root', sa.String(length=512), nullable=True),
        sa.Column('pack_base_url', sa.String(length=512), nullable=True),
        sa.Column('manifest_url', sa.String(length=512), nullable=True),
        sa.Column('pack_version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('min_launcher_version', sa.String(length=32), nullable=False, server_default='0.1.0'),
        sa.Column('status_host', sa.String(length=255), nullable=True),
        sa.Column('status_port', sa.Integer(), nullable=True),
        sa.Column('max_players', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('whitelist_mode', sa.String(length=16), nullable=False, server_default='public'),
        sa.Column('maintenance', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('game_auth_secret', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_game_servers')),
        sa.UniqueConstraint('slug', name=op.f('uq_game_servers_slug')),
        sa.UniqueConstraint('game_auth_secret', name=op.f('uq_game_servers_game_auth_secret')),
    )
    op.create_index(op.f('ix_game_servers_slug'), 'game_servers', ['slug'])
    op.create_index(op.f('ix_game_servers_is_default'), 'game_servers', ['is_default'])

    # ── Seed the existing (default) server ────────────────────────────────
    # Bind its game_auth_secret to the current global GAME_AUTH_SHARED_SECRET
    # so all existing plugins/mods keep authenticating during migration.
    from apps.api.app.config import get_settings

    default_secret = get_settings().game_auth_shared_secret

    game_servers = sa.table(
        'game_servers',
        sa.column('id', sa.Uuid()),
        sa.column('slug', sa.String()),
        sa.column('name', sa.String()),
        sa.column('description', sa.Text()),
        sa.column('sort_order', sa.Integer()),
        sa.column('is_visible', sa.Boolean()),
        sa.column('is_default', sa.Boolean()),
        sa.column('host', sa.String()),
        sa.column('port', sa.Integer()),
        sa.column('mc_version', sa.String()),
        sa.column('loader', sa.String()),
        sa.column('java_version', sa.Integer()),
        sa.column('neoforge_version', sa.String()),
        sa.column('pack_root', sa.String()),
        sa.column('pack_base_url', sa.String()),
        sa.column('manifest_url', sa.String()),
        sa.column('pack_version', sa.String()),
        sa.column('min_launcher_version', sa.String()),
        sa.column('max_players', sa.Integer()),
        sa.column('whitelist_mode', sa.String()),
        sa.column('game_auth_secret', sa.String()),
    )
    op.bulk_insert(
        game_servers,
        [
            {
                'id': uuid.uuid4(),
                'slug': 'voidrp',
                'name': 'VoidRP',
                'description': 'Основной сервер VoidRP (Better MC 5).',
                'sort_order': 0,
                'is_visible': True,
                'is_default': True,
                'host': 'void-rp.ru',
                'port': 25565,
                'mc_version': '1.21.1',
                'loader': 'neoforge',
                'java_version': 21,
                'neoforge_version': '21.1.232',
                'pack_root': '/home/mironoouv/launcher/pack',
                'pack_base_url': 'https://void-rp.ru/launcher/pack',
                'manifest_url': 'https://void-rp.ru/launcher/manifests/manifest.json',
                'pack_version': '1.0.0',
                'min_launcher_version': '0.1.0',
                'max_players': 100,
                'whitelist_mode': 'public',
                'game_auth_secret': default_secret,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_game_servers_is_default'), table_name='game_servers')
    op.drop_index(op.f('ix_game_servers_slug'), table_name='game_servers')
    op.drop_table('game_servers')
