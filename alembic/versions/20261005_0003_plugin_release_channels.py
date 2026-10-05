"""plugin_releases: channel, yanked, important, and where a build came from (GitHub)

Revision ID: 20261005_0003
Revises: 20261005_0002
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_0003"
down_revision = "20261005_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugin_releases", sa.Column("channel", sa.String(8), nullable=False, server_default="stable"))
    op.add_column("plugin_releases", sa.Column("yanked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("plugin_releases", sa.Column("important", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("plugin_releases", sa.Column("source", sa.String(8), nullable=False, server_default="manual"))
    op.add_column("plugin_releases", sa.Column("github_asset_id", sa.BigInteger(), nullable=True))
    op.add_column("plugin_releases", sa.Column("source_url", sa.String(512), nullable=True))
    op.create_unique_constraint("uq_plugin_releases_github_asset", "plugin_releases", ["github_asset_id"])


def downgrade() -> None:
    op.drop_constraint("uq_plugin_releases_github_asset", "plugin_releases", type_="unique")
    for col in ("source_url", "github_asset_id", "source", "important", "yanked", "channel"):
        op.drop_column("plugin_releases", col)
