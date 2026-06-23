"""add launcher_preferences table

Revision ID: 20260514_0021
Revises: 20260510_0020
Create Date: 2026-05-14

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260514_0021"
down_revision = "20260510_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "launcher_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("disabled_mods_json", sa.Text(), nullable=False, server_default="'[]'"),
        sa.Column("config_files_json", sa.Text(), nullable=False, server_default="'{}'"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_launcher_preferences_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_launcher_preferences"),
        sa.UniqueConstraint("user_id", name="uq_launcher_preferences_user_id"),
    )


def downgrade() -> None:
    op.drop_table("launcher_preferences")
