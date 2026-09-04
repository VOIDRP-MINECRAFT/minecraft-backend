"""battlepass_seasons: admin-managed seasons (dates, level cap, active flag)

Revision ID: 20260902_0002
Revises: 20260902_0001
Create Date: 2026-09-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260902_0002"
down_revision = "20260902_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "battlepass_seasons",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("game_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season_key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("max_level", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "season_key", name="uq_battlepass_seasons_key"),
    )
    op.create_index("ix_battlepass_seasons_server_id", "battlepass_seasons", ["server_id"])


def downgrade() -> None:
    op.drop_index("ix_battlepass_seasons_server_id", table_name="battlepass_seasons")
    op.drop_table("battlepass_seasons")
