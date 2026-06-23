"""add battlepass_progress table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "battlepass_progress",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("minecraft_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("minecraft_nickname", sa.String(64), nullable=False, server_default=""),
        sa.Column("season", sa.String(8), nullable=False),
        sa.Column("level", sa.Integer, nullable=False, server_default="1"),
        sa.Column("xp", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_battlepass_progress_minecraft_uuid",
                    "battlepass_progress", ["minecraft_uuid"])
    op.create_index("ix_battlepass_progress_minecraft_nickname",
                    "battlepass_progress", ["minecraft_nickname"])


def downgrade() -> None:
    op.drop_index("ix_battlepass_progress_minecraft_nickname", "battlepass_progress")
    op.drop_index("ix_battlepass_progress_minecraft_uuid", "battlepass_progress")
    op.drop_table("battlepass_progress")
