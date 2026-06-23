"""add play tickets

Revision ID: 20260408_0002
Revises: 20260406_0001
Create Date: 2026-04-08 13:50:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260408_0002"
down_revision = "20260406_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "play_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("minecraft_nickname", sa.String(length=16), nullable=False),
        sa.Column("ticket_hash", sa.String(length=128), nullable=False),
        sa.Column("launcher_version", sa.String(length=32), nullable=True),
        sa.Column("launcher_platform", sa.String(length=64), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_play_tickets_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_play_tickets"),
        sa.UniqueConstraint("ticket_hash", name="uq_play_tickets_ticket_hash"),
    )
    op.create_index("ix_play_tickets_user_id", "play_tickets", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_play_tickets_user_id", table_name="play_tickets")
    op.drop_table("play_tickets")