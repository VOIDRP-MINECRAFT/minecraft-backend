"""figura_cosmetics: preview_url (shop preview image)

Revision ID: 20260903_0001
Revises: 20260902_0002
Create Date: 2026-09-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260903_0001"
down_revision = "20260902_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("figura_cosmetics", sa.Column("preview_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("figura_cosmetics", "preview_url")
