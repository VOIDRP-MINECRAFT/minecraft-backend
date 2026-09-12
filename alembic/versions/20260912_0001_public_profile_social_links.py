"""player_public_profiles: social links (Twitch, YouTube, Telegram, ...)

A flat ``{platform: url}`` map. Which platforms exist and which hosts each one
accepts is decided in ``schemas/profile.py`` (SOCIAL_LINK_HOSTS), not in the
database, so adding a platform needs no migration.

Existing rows get ``{}`` — no behaviour change on deploy.

Revision ID: 20260912_0001
Revises: 20260910_0001
Create Date: 2026-09-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260912_0001"
down_revision = "20260910_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player_public_profiles",
        sa.Column(
            "social_links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("player_public_profiles", "social_links")
