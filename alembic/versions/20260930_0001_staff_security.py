"""staff security: devices (sign-ins), 2FA, password re-confirmation

``auth_devices``: one sign-in on one device — survives the refresh-token rotation (each
refresh makes a new ``refresh_sessions`` row, all tied to the same device). Holds what
the «Активные входы» list shows (user agent, IP, city) and the device's 2FA and password
re-confirmation marks. ``users``: 2FA settings (TOTP secret encrypted, Telegram codes,
hashed backup codes). Additive only.

Revision ID: 20260930_0001
Revises: 20260929_0013
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0001"
down_revision = "20260929_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("device_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("location", sa.String(160), nullable=True),
        sa.Column("last_ip", sa.String(64), nullable=True),
        sa.Column("last_location", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reauth_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_code_hash", sa.String(128), nullable=True),
        sa.Column("mfa_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("refresh_sessions", sa.Column("device_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_refresh_sessions_device_id_auth_devices", "refresh_sessions", "auth_devices",
                          ["device_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_refresh_sessions_device_id", "refresh_sessions", ["device_id"])
    op.add_column("users", sa.Column("mfa_totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("mfa_telegram_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("mfa_backup_hashes", postgresql.JSONB(), nullable=False,
                                     server_default=sa.text("'[]'::jsonb")))
    op.add_column("users", sa.Column("mfa_totp_last_step", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    for col in ("mfa_totp_last_step", "mfa_backup_hashes", "mfa_telegram_enabled_at", "mfa_totp_enabled_at", "mfa_totp_secret"):
        op.drop_column("users", col)
    op.drop_index("ix_refresh_sessions_device_id", table_name="refresh_sessions")
    op.drop_constraint("fk_refresh_sessions_device_id_auth_devices", "refresh_sessions", type_="foreignkey")
    op.drop_column("refresh_sessions", "device_id")
    op.drop_table("auth_devices")
