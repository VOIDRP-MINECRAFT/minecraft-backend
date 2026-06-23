"""add mod_suggestions table

Revision ID: 20260515_0023
Revises: 20260515_0022
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260515_0023"
down_revision = "20260515_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mod_suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_mod_suggestions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mod_suggestions"),
    )
    op.create_index("ix_mod_suggestions_user_id", "mod_suggestions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mod_suggestions_user_id", table_name="mod_suggestions")
    op.drop_table("mod_suggestions")
