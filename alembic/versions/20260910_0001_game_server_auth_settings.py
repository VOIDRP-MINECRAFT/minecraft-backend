"""game_servers: per-server authentication timeouts

Moves the login-related timeouts out of the backend ``.env``
(``PLAY_TICKET_EXPIRE_MINUTES``) and the JVM ``-Dvoidrp.auth.*`` flags in
youer.service into the database, so the admin panel can change them live.

Existing rows get ``{}`` and therefore fall back to DEFAULT_AUTH_SETTINGS in
``resolve_auth_settings`` — no behaviour change on deploy.

Revision ID: 20260910_0001
Revises: 20260903_0002
Create Date: 2026-09-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260910_0001"
down_revision = "20260903_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_servers",
        sa.Column(
            "auth_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("game_servers", "auth_settings")
