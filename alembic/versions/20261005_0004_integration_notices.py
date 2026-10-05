"""integration_notices (each announcement once) and users.integration_notify (what to hear)

Revision ID: 20261005_0004
Revises: 20261005_0003
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261005_0004"
down_revision = "20261005_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_notices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("ref", sa.String(128), nullable=False),
        sa.Column("telegram_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "user_id", "kind", "ref", name="uq_integration_notices_once"),
    )
    op.create_index("ix_integration_notices_server_id", "integration_notices", ["server_id"])
    op.create_index("ix_integration_notices_user_id", "integration_notices", ["user_id"])
    op.add_column("users", sa.Column("integration_notify", postgresql.JSONB(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("users", "integration_notify")
    op.drop_index("ix_integration_notices_user_id", table_name="integration_notices")
    op.drop_index("ix_integration_notices_server_id", table_name="integration_notices")
    op.drop_table("integration_notices")
