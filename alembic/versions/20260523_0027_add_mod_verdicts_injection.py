"""add mod_verdicts and anticheat_injection_reports

Revision ID: 20260523_0027
Revises: 20260522_0026
Create Date: 2026-05-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260523_0027"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mod_verdicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mod_id", sa.String(128), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_mod_verdicts"),
        sa.UniqueConstraint("mod_id", name="uq_mod_verdicts_mod_id"),
    )
    op.create_index("ix_mod_verdicts_mod_id", "mod_verdicts", ["mod_id"])

    op.create_table(
        "anticheat_injection_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_uuid", sa.String(36), nullable=False),
        sa.Column("player_nick", sa.String(64), nullable=False),
        sa.Column("java_agents", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("suspicious_libraries", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("agents_detected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_anticheat_injection_reports"),
    )
    op.create_index("ix_anticheat_injection_reports_player_uuid", "anticheat_injection_reports", ["player_uuid"])
    op.create_index("ix_anticheat_injection_reports_player_nick", "anticheat_injection_reports", ["player_nick"])


def downgrade() -> None:
    op.drop_table("anticheat_injection_reports")
    op.drop_table("mod_verdicts")
