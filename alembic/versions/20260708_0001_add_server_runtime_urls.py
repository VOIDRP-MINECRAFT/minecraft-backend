"""add per-server runtime seed / manifest urls

Revision ID: 20260708_0001
Revises: 20260707_0004
Create Date: 2026-07-08

Adds ``runtime_seed_url`` and ``runtime_manifest_url`` to ``game_servers``.
The launcher bootstraps the Java runtime for the selected server from these;
null falls back to the launcher-global endpoints (appsettings).

The default server is backfilled with the current production URLs (the same
ones hardcoded in the launcher's appsettings), so behaviour is unchanged.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260708_0001"
down_revision = "20260707_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("runtime_seed_url", sa.String(length=512), nullable=True))
    op.add_column("game_servers", sa.Column("runtime_manifest_url", sa.String(length=512), nullable=True))
    op.execute(
        "UPDATE game_servers SET "
        "runtime_seed_url = 'https://void-rp.ru/launcher/runtime-seed', "
        "runtime_manifest_url = 'https://void-rp.ru/launcher/manifests' "
        "WHERE is_default = true"
    )


def downgrade() -> None:
    op.drop_column("game_servers", "runtime_manifest_url")
    op.drop_column("game_servers", "runtime_seed_url")
