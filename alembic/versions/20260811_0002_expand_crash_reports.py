"""expand_launcher_crash_reports with diagnostics

Revision ID: 20260811_0002
Revises: 20260811_0001
Create Date: 2026-08-11

Adds richer diagnostics to launcher crash reports: the tail of the game log
(present even when no crash-report file was written — the common OOM case),
plus environment info (OS / Java / RAM / launcher version / server slug).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260811_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launcher_crash_reports", sa.Column("log_tail", sa.Text(), nullable=True))
    op.add_column("launcher_crash_reports", sa.Column("launcher_version", sa.String(32), nullable=True))
    op.add_column("launcher_crash_reports", sa.Column("os_name", sa.String(120), nullable=True))
    op.add_column("launcher_crash_reports", sa.Column("java_version", sa.String(120), nullable=True))
    op.add_column("launcher_crash_reports", sa.Column("ram_mb", sa.Integer(), nullable=True))
    op.add_column("launcher_crash_reports", sa.Column("server_slug", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("launcher_crash_reports", "server_slug")
    op.drop_column("launcher_crash_reports", "ram_mb")
    op.drop_column("launcher_crash_reports", "java_version")
    op.drop_column("launcher_crash_reports", "os_name")
    op.drop_column("launcher_crash_reports", "launcher_version")
    op.drop_column("launcher_crash_reports", "log_tail")
