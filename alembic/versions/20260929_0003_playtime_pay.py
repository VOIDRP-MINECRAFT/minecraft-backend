"""pay for playing: per-server settings and the payouts

New tables only; nothing existing changes.

Revision ID: 20260929_0003
Revises: 20260929_0002
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_0003"
down_revision = "20260929_0002"
branch_labels = None
depends_on = None


def _server_fk():
    return sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True)


def _stamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "playtime_pay_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("server_id", name="uq_playtime_pay_settings_server"),
    )
    op.create_table(
        "playtime_payouts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("claim_id", sa.String(64), nullable=False),
        sa.Column("player_uuid", sa.String(36), nullable=False),
        sa.Column("player_name", sa.String(64), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        *_stamps(),
        sa.UniqueConstraint("server_id", "claim_id", name="uq_playtime_payouts_claim"),
    )
    op.create_index("ix_playtime_payouts_server_day_player", "playtime_payouts", ["server_id", "day", "player_uuid"])


def downgrade() -> None:
    op.drop_index("ix_playtime_payouts_server_day_player", table_name="playtime_payouts")
    op.drop_table("playtime_payouts")
    op.drop_table("playtime_pay_settings")
