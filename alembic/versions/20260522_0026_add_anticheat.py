"""add anticheat tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anticheat_violations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("player_uuid", sa.String(36), nullable=False),
        sa.Column("player_nick", sa.String(64), nullable=False),
        sa.Column("check_type", sa.String(32), nullable=False),
        sa.Column("details", sa.Text, nullable=False, server_default=""),
        sa.Column("actual_value", sa.Float, nullable=False, server_default="0"),
        sa.Column("expected_max", sa.Float, nullable=False, server_default="0"),
        sa.Column("vl", sa.Integer, nullable=False, server_default="0"),
        sa.Column("severity", sa.String(8), nullable=False, server_default="LOW"),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("review_action", sa.String(16), nullable=True),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_anticheat_violations_player_uuid", "anticheat_violations", ["player_uuid"])
    op.create_index("ix_anticheat_violations_player_nick", "anticheat_violations", ["player_nick"])
    op.create_index("ix_anticheat_violations_created_at", "anticheat_violations", ["created_at"])

    op.create_table(
        "anticheat_mod_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("player_uuid", sa.String(36), nullable=False),
        sa.Column("player_nick", sa.String(64), nullable=False),
        sa.Column("mods", sa.Text, nullable=False, server_default="[]"),
        sa.Column("suspicious_mods", sa.Text, nullable=False, server_default="[]"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("resource_pack_status", sa.String(16), nullable=False, server_default="NONE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_anticheat_mod_snapshots_player_uuid", "anticheat_mod_snapshots", ["player_uuid"])
    op.create_index("ix_anticheat_mod_snapshots_player_nick", "anticheat_mod_snapshots", ["player_nick"])


def downgrade() -> None:
    op.drop_index("ix_anticheat_mod_snapshots_player_nick", "anticheat_mod_snapshots")
    op.drop_index("ix_anticheat_mod_snapshots_player_uuid", "anticheat_mod_snapshots")
    op.drop_table("anticheat_mod_snapshots")
    op.drop_index("ix_anticheat_violations_created_at", "anticheat_violations")
    op.drop_index("ix_anticheat_violations_player_nick", "anticheat_violations")
    op.drop_index("ix_anticheat_violations_player_uuid", "anticheat_violations")
    op.drop_table("anticheat_violations")
