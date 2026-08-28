"""create nation_research table (nation tech tree)

Revision ID: 20260828_0001
Revises: 20260827_0001
Create Date: 2026-08-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_0001"
down_revision = "20260827_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nation_research",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("nation_id", sa.UUID(), nullable=False),
        sa.Column("research_key", sa.String(64), nullable=False),
        sa.Column("level", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name="fk_nation_research_server_id_game_servers", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["nation_id"], ["nations.id"],
            name="fk_nation_research_nation_id_nations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nation_research"),
        sa.UniqueConstraint("nation_id", "research_key", name="uq_nation_research_nation_id"),
    )
    op.create_index("ix_nation_research_server_id", "nation_research", ["server_id"])
    op.create_index("ix_nation_research_nation_id", "nation_research", ["nation_id"])


def downgrade() -> None:
    op.drop_index("ix_nation_research_nation_id", table_name="nation_research")
    op.drop_index("ix_nation_research_server_id", table_name="nation_research")
    op.drop_table("nation_research")
