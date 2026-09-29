"""prefix-search indexes for nickname suggestions in the admin panel

``LIKE 'abc%'`` can use a btree index only with ``text_pattern_ops`` (the database
collation is not C). Additive only.

Revision ID: 20260929_0013
Revises: 20260929_0012
Create Date: 2026-09-29
"""
from __future__ import annotations

from alembic import op

revision = "20260929_0013"
down_revision = "20260929_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_site_login_prefix ON users (site_login_normalized text_pattern_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_player_accounts_nick_prefix "
               "ON player_accounts (minecraft_nickname_normalized text_pattern_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_player_accounts_nick_prefix")
    op.execute("DROP INDEX IF EXISTS ix_users_site_login_prefix")
