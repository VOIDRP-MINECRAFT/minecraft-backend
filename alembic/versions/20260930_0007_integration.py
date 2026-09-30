"""integration of external servers: plugin releases, server core

* ``plugin_releases`` — every published build of our plugins and mods: version, platforms,
  Minecraft versions, what changed, file and sha256, which one is recommended;
* ``game_servers.server_core`` — what the server itself runs (paper | folia | neoforge |
  hybrid), apart from ``loader``, which describes the client pack the launcher installs.
  It picks the login method a partner is told to install: a plugin core gets VoidRpAuth,
  a modded or hybrid one the voidrp-auth-bridge mod.

Revision ID: 20260930_0007
Revises: 20260930_0006
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0007"
down_revision = "20260930_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plugin", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("platforms", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("mc_versions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_by", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("plugin", "version", "filename", name="uq_plugin_releases_plugin_version_file"),
    )
    op.create_index("ix_plugin_releases_plugin", "plugin_releases", ["plugin"])
    op.add_column("game_servers", sa.Column("server_core", sa.String(16), nullable=True))
    bind = op.get_bind()
    # What runs today: the main server is Youer (NeoForge + Paper hybrid); Origins and VexVol
    # run Paper 26.2.
    bind.execute(sa.text("update game_servers set server_core = 'hybrid' where slug = 'voidrp'"))
    bind.execute(sa.text("update game_servers set server_core = 'paper' where slug in ('origins', 'vexvol')"))


def downgrade() -> None:
    op.drop_column("game_servers", "server_core")
    op.drop_index("ix_plugin_releases_plugin", table_name="plugin_releases")
    op.drop_table("plugin_releases")
