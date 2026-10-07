"""server_file_jobs: file operations for partner servers' VoidRpPerms (modules.files)

Revision ID: 20261007_0001
Revises: 20261006_0006
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0001"
down_revision = "20261006_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_file_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_server_file_jobs_server_id", "server_file_jobs", ["server_id"])
    op.create_index("ix_server_file_jobs_status", "server_file_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("server_file_jobs")
