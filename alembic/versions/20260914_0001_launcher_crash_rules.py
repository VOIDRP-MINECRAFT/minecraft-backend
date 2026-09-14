"""launcher crash rules: admin-editable crash recognition for the launcher

* ``launcher_crash_rules`` — rules the launcher downloads and merges over its built-ins.
* ``game_servers.launcher_recommended_ram_mb`` — pre-launch memory warning threshold.
* ``launcher_crash_reports.advice_rule_key`` — which rule recognized a reported crash.

No data changes: existing servers get NULL (launcher default), existing reports NULL.

Revision ID: 20260914_0001
Revises: 20260912_0001
Create Date: 2026-09-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260914_0001"
down_revision = "20260912_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "launcher_crash_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("patterns_all", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("patterns_any", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("exit_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False, server_default=""),
        sa.Column("solution", sa.Text(), nullable=False, server_default=""),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_launcher_crash_rules_server_id", "launcher_crash_rules", ["server_id"])
    op.create_index("ix_launcher_crash_rules_key", "launcher_crash_rules", ["key"])

    op.add_column("game_servers", sa.Column("launcher_recommended_ram_mb", sa.Integer(), nullable=True))

    op.add_column("launcher_crash_reports", sa.Column("advice_rule_key", sa.String(64), nullable=True))
    op.create_index("ix_launcher_crash_reports_advice_rule_key", "launcher_crash_reports", ["advice_rule_key"])


def downgrade() -> None:
    op.drop_index("ix_launcher_crash_reports_advice_rule_key", table_name="launcher_crash_reports")
    op.drop_column("launcher_crash_reports", "advice_rule_key")
    op.drop_column("game_servers", "launcher_recommended_ram_mb")
    op.drop_index("ix_launcher_crash_rules_key", table_name="launcher_crash_rules")
    op.drop_index("ix_launcher_crash_rules_server_id", table_name="launcher_crash_rules")
    op.drop_table("launcher_crash_rules")
