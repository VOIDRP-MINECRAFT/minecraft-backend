"""royale_matches — battle royale results that outlive their server

Revision ID: 20261013_0001
Revises: 20261007_0001
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261013_0001"
down_revision = "20261007_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "royale_matches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("server_slug", sa.String(64), nullable=False),
        sa.Column("match_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("map", sa.String(64), nullable=False),
        sa.Column("map_title", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aborted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("winner", sa.String(32), nullable=True),
        sa.Column("winner_title", sa.String(64), nullable=True),
        sa.Column("teams_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("players_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_royale_matches_server_id", "royale_matches", ["server_id"])
    op.create_index("ix_royale_matches_server_slug", "royale_matches", ["server_slug"])
    op.create_index("ix_royale_matches_started_at", "royale_matches", ["started_at"])


def downgrade() -> None:
    op.drop_table("royale_matches")
