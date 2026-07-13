"""create kill_events (anarchy PvP killfeed)

Revision ID: 20260713_0002
Revises: 20260713_0001
Create Date: 2026-07-13

Append-only log of PvP kills for the public killfeed. Stores only killer/victim/weapon
(never coordinates) so it is anarchy-safe. Server-scoped.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kill_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="pvp"),
        sa.Column("killer_nick", sa.String(length=16), nullable=False),
        sa.Column("killer_user_id", sa.Uuid(), nullable=True),
        sa.Column("victim_nick", sa.String(length=16), nullable=False),
        sa.Column("victim_user_id", sa.Uuid(), nullable=True),
        sa.Column("weapon", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["killer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["victim_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kill_events")),
    )
    op.create_index(op.f("ix_kill_events_server_id"), "kill_events", ["server_id"])
    op.create_index(op.f("ix_kill_events_killer_user_id"), "kill_events", ["killer_user_id"])
    op.create_index(op.f("ix_kill_events_victim_user_id"), "kill_events", ["victim_user_id"])
    op.create_index(op.f("ix_kill_events_created_at"), "kill_events", ["created_at"])
    op.create_index("ix_kill_events_server_created", "kill_events", ["server_id", "created_at"])


def downgrade() -> None:
    op.drop_table("kill_events")
