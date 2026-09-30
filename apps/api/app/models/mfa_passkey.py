from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class MfaPasskey(UuidPrimaryKeyMixin, Base):
    """A passkey (WebAuthn credential) used as 2FA: Windows Hello, Face ID / Touch ID,
    Android screen lock, a security key, or one kept by a password manager."""

    __tablename__ = "mfa_passkeys"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)  # base64url
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transports: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Synced between the person's devices (iCloud Keychain, Google Password Manager…).
    synced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
