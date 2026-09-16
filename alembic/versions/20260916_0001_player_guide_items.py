"""player guide items: key progression items each player has held (in-game roadmap)

New table only; nothing existing changes.

Revision ID: 20260916_0001
Revises: 20260915_0001
Create Date: 2026-09-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260916_0001"
down_revision = "20260915_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_guide_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("minecraft_nickname_normalized", sa.String(64), nullable=False),
        sa.Column("minecraft_uuid", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(128), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "minecraft_nickname_normalized", "item_id", name="uq_player_guide_items_item"),
    )
    op.create_index("ix_player_guide_items_server_id", "player_guide_items", ["server_id"])
    op.create_index("ix_player_guide_items_minecraft_nickname_normalized", "player_guide_items", ["minecraft_nickname_normalized"])


def downgrade() -> None:
    op.drop_index("ix_player_guide_items_minecraft_nickname_normalized", table_name="player_guide_items")
    op.drop_index("ix_player_guide_items_server_id", table_name="player_guide_items")
    op.drop_table("player_guide_items")
