"""user consents: log of accepted offer, personal data and distribution consents

New table only; nothing existing changes.

Revision ID: 20260917_0001
Revises: 20260916_0001
Create Date: 2026-09-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_0001"
down_revision = "20260916_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_consents_user_document", "user_consents", ["user_id", "document", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_consents_user_document", table_name="user_consents")
    op.drop_table("user_consents")
