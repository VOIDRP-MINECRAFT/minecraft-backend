"""add player skins

Revision ID: 20260423_0012
Revises: 20260417_0011
Create Date: 2026-04-23 23:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260423_0012"
down_revision = "20260417_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_skins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("model_variant", sa.String(length=16), nullable=False, server_default="classic"),
        sa.Column("mime_type", sa.String(length=64), nullable=False, server_default="image/png"),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="64"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="64"),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_storage_key", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.String(length=512), nullable=False),
        sa.Column("head_preview_storage_key", sa.String(length=255), nullable=True),
        sa.Column("head_preview_url", sa.String(length=512), nullable=True),
        sa.Column("body_preview_storage_key", sa.String(length=255), nullable=True),
        sa.Column("body_preview_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_player_skins_user_id"),
    )
    op.create_index("ix_player_skins_user_id", "player_skins", ["user_id"], unique=False)
    op.create_index("ix_player_skins_sha256", "player_skins", ["sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_player_skins_sha256", table_name="player_skins")
    op.drop_index("ix_player_skins_user_id", table_name="player_skins")
    op.drop_table("player_skins")
