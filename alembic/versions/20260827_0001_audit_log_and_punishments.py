"""create admin_audit_log and punishments tables

Revision ID: 20260827_0001
Revises: 20260824_0002
Create Date: 2026-08-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260827_0001"
down_revision = "20260824_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(48), nullable=True),
        sa.Column("target_id", sa.String(120), nullable=True),
        sa.Column("target_label", sa.String(200), nullable=True),
        sa.Column("server_id", sa.UUID(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_admin_audit_log_actor_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_admin_audit_log_server_id_game_servers", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audit_log"),
    )
    op.create_index("ix_admin_audit_log_actor_user_id", "admin_audit_log", ["actor_user_id"])
    op.create_index("ix_admin_audit_log_category", "admin_audit_log", ["category"])
    op.create_index("ix_admin_audit_log_target_id", "admin_audit_log", ["target_id"])
    op.create_index("ix_admin_audit_log_server_id", "admin_audit_log", ["server_id"])
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])

    op.create_table(
        "punishments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=True),
        sa.Column("player_uuid", sa.String(36), nullable=True),
        sa.Column("player_name", sa.String(64), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("issued_by_user_id", sa.UUID(), nullable=True),
        sa.Column("issued_by_name", sa.String(120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_name", sa.String(120), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], name="fk_punishments_server_id_game_servers", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], name="fk_punishments_issued_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_punishments"),
    )
    op.create_index("ix_punishments_server_id", "punishments", ["server_id"])
    op.create_index("ix_punishments_player_uuid", "punishments", ["player_uuid"])
    op.create_index("ix_punishments_player_name", "punishments", ["player_name"])
    op.create_index("ix_punishments_active", "punishments", ["active"])
    op.create_index("ix_punishments_created_at", "punishments", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_punishments_created_at", table_name="punishments")
    op.drop_index("ix_punishments_active", table_name="punishments")
    op.drop_index("ix_punishments_player_name", table_name="punishments")
    op.drop_index("ix_punishments_player_uuid", table_name="punishments")
    op.drop_index("ix_punishments_server_id", table_name="punishments")
    op.drop_table("punishments")

    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_server_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_target_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_category", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_actor_user_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
