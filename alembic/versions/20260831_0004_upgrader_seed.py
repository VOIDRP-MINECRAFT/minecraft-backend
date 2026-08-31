"""upgrader commit-reveal per-player active server seed

Revision ID: 20260831_0004
Revises: 20260831_0003
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260831_0004"
down_revision = "20260831_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "void_upgrader_seed",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("server_seed", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_seed_server", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_void_upgrader_seed_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "user_id", name="uq_void_upgrader_seed_server_user"),
    )
    op.create_index("ix_void_upgrader_seed_user", "void_upgrader_seed", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_void_upgrader_seed_user", table_name="void_upgrader_seed")
    op.drop_table("void_upgrader_seed")
