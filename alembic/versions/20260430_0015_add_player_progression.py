"""add player progression

Revision ID: 20260430_0015
Revises: 20260429_0014
Create Date: 2026-04-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260430_0015"
down_revision = "20260429_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_progressions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(64), nullable=False),
        sa.Column("minecraft_nickname_normalized", sa.String(64), nullable=False),
        sa.Column("minecraft_uuid", sa.String(36), nullable=False),
        sa.Column("tier_name", sa.String(64), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_progressions")),
        sa.UniqueConstraint(
            "minecraft_nickname_normalized",
            "tier_name",
            name="uq_player_progression_tier",
        ),
    )
    op.create_index(
        op.f("ix_player_progressions_minecraft_nickname"),
        "player_progressions",
        ["minecraft_nickname"],
    )
    op.create_index(
        op.f("ix_player_progressions_minecraft_nickname_normalized"),
        "player_progressions",
        ["minecraft_nickname_normalized"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_player_progressions_minecraft_nickname_normalized"),
        table_name="player_progressions",
    )
    op.drop_index(
        op.f("ix_player_progressions_minecraft_nickname"),
        table_name="player_progressions",
    )
    op.drop_table("player_progressions")
