"""add battlepass_premium table

Revision ID: a1b2c3d4e5f6
Revises: 20260515_0023
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "20260515_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "battlepass_premium",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("minecraft_uuid", sa.String(36), nullable=False),
        sa.Column("minecraft_nickname", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", sa.String(64), nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_battlepass_premium"),
        sa.UniqueConstraint("minecraft_uuid", name="uq_battlepass_premium_minecraft_uuid"),
    )
    op.create_index(
        "ix_battlepass_premium_minecraft_uuid",
        "battlepass_premium",
        ["minecraft_uuid"],
    )


def downgrade() -> None:
    op.drop_index("ix_battlepass_premium_minecraft_uuid", table_name="battlepass_premium")
    op.drop_table("battlepass_premium")
