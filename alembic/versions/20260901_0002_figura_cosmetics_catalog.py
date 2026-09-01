"""figura cosmetics catalog + ownership

Revision ID: 20260901_0002
Revises: 20260901_0001
Create Date: 2026-09-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260901_0002"
down_revision = "20260901_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "figura_cosmetics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slot", sa.String(length=24), nullable=False, server_default="full"),
        sa.Column("price_void_coins", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_figura_cosmetics_slug"),
    )
    op.create_table(
        "figura_cosmetic_owned",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("cosmetic_slug", sa.String(length=64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_figura_cosmetic_owned_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "cosmetic_slug", name="uq_figura_cosmetic_owned"),
    )
    op.create_index("ix_figura_cosmetic_owned_user", "figura_cosmetic_owned", ["user_id"])
    op.create_index("ix_figura_cosmetic_owned_slug", "figura_cosmetic_owned", ["cosmetic_slug"])


def downgrade() -> None:
    op.drop_table("figura_cosmetic_owned")
    op.drop_table("figura_cosmetics")
