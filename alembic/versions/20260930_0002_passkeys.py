"""passkeys (WebAuthn) as a 2FA method: Windows Hello, Face ID / Touch ID, Android,
security keys, password managers

``mfa_passkeys`` — a person's registered keys; ``auth_devices`` gets the pending WebAuthn
challenge. Additive only.

Revision ID: 20260930_0002
Revises: 20260930_0001
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0002"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_passkeys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("credential_id", sa.String(512), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("transports", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("synced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("auth_devices", sa.Column("webauthn_challenge", sa.String(200), nullable=True))
    op.add_column("auth_devices", sa.Column("webauthn_challenge_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_devices", "webauthn_challenge_expires_at")
    op.drop_column("auth_devices", "webauthn_challenge")
    op.drop_table("mfa_passkeys")
