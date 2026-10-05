"""skin_textures: player skins signed by Mojang (through MineSkin)

Revision ID: 20261005_0002
Revises: 20261005_0001
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_0002"
down_revision = "20261005_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skin_textures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("model_variant", sa.String(16), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("mineskin_uuid", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("sha256", "model_variant", name="uq_skin_textures_sha_variant"),
    )
    op.create_index("ix_skin_textures_sha256", "skin_textures", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_skin_textures_sha256", table_name="skin_textures")
    op.drop_table("skin_textures")
