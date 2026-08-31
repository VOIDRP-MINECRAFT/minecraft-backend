"""self-hosted figura backend tables

Revision ID: 20260901_0001
Revises: 20260831_0005
Create Date: 2026-09-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260901_0001"
down_revision = "20260831_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "figura_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=96), nullable=False),
        sa.Column("minecraft_uuid", sa.String(length=36), nullable=False),
        sa.Column("minecraft_nickname", sa.String(length=48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_figura_sessions_token", "figura_sessions", ["token"], unique=True)
    op.create_index("ix_figura_sessions_minecraft_uuid", "figura_sessions", ["minecraft_uuid"])

    op.create_table(
        "figura_avatars",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_uuid", sa.String(length=36), nullable=False),
        sa.Column("avatar_id", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_cosmetic", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_uuid", "avatar_id", name="uq_figura_avatars_owner_id"),
    )
    op.create_index("ix_figura_avatars_owner_uuid", "figura_avatars", ["owner_uuid"])

    op.create_table(
        "figura_equipped",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_uuid", sa.String(length=36), nullable=False),
        sa.Column("equipped", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_uuid", name="uq_figura_equipped_owner"),
    )
    op.create_index("ix_figura_equipped_owner_uuid", "figura_equipped", ["owner_uuid"])


def downgrade() -> None:
    op.drop_table("figura_equipped")
    op.drop_table("figura_avatars")
    op.drop_table("figura_sessions")
