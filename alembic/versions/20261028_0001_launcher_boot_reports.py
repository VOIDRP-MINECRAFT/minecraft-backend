"""launcher_boot_reports — launchers that could not start, reported without an account

Revision ID: 20261028_0001
Revises: 20261021_0001
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "20261028_0001"
down_revision = "20261021_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "launcher_boot_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("launcher_version", sa.String(32), nullable=True),
        sa.Column("os_name", sa.String(160), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("main_log_tail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_launcher_boot_reports_launcher_version", "launcher_boot_reports", ["launcher_version"])
    op.create_index("ix_launcher_boot_reports_created_at", "launcher_boot_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_launcher_boot_reports_created_at", table_name="launcher_boot_reports")
    op.drop_index("ix_launcher_boot_reports_launcher_version", table_name="launcher_boot_reports")
    op.drop_table("launcher_boot_reports")
