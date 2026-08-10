"""add game_servers.manifest_build_script (de-hardcode manifest rebuild)

Revision ID: 20260811_0001
Revises: 20260810_0002
Create Date: 2026-08-11

Moves the per-server manifest-rebuild dispatch out of code (was `if slug ==
"abyss"`) into data. Null → standard DB-driven generator; a path (under scripts/)
→ run that bash script. Backfills abyss with its existing script so the "Моды"
rebuild button keeps working.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260811_0001"
down_revision = "20260810_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_servers",
        sa.Column("manifest_build_script", sa.String(length=512), nullable=True),
    )
    op.execute(
        "UPDATE game_servers SET manifest_build_script = 'scripts/generate_abyss_manifests.sh' "
        "WHERE slug = 'abyss'"
    )


def downgrade() -> None:
    op.drop_column("game_servers", "manifest_build_script")
