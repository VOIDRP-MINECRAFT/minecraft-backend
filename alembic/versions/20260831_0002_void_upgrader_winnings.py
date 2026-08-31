"""create void_upgrader_winnings table

Revision ID: 20260831_0002
Revises: 20260831_0001
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260831_0002"
down_revision = "20260831_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "void_upgrader_winnings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(length=48), nullable=False),
        sa.Column("item_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("vc_value", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tier", sa.String(length=24), server_default="common", nullable=False),
        sa.Column("give_command", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_void_upgrader_winnings_server", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_void_upgrader_winnings_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_void_upgrader_winnings_user", "void_upgrader_winnings", ["user_id"])
    op.create_index("ix_void_upgrader_winnings_server_user", "void_upgrader_winnings", ["server_id", "user_id"])


def downgrade() -> None:
    op.drop_index("ix_void_upgrader_winnings_server_user", table_name="void_upgrader_winnings")
    op.drop_index("ix_void_upgrader_winnings_user", table_name="void_upgrader_winnings")
    op.drop_table("void_upgrader_winnings")
