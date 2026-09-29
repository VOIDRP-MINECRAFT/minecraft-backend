from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class AuthDevice(UuidPrimaryKeyMixin, Base):
    """One sign-in on one device. Refresh tokens rotate (a new ``refresh_sessions`` row
    each time); they all point here, so the device keeps its identity (the ``sid`` in
    access tokens), its 2FA mark and its place in «Активные входы»."""

    __tablename__ = "auth_devices"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When 2FA was last passed on this device (admin panel access lasts MFA_TTL), and the
    # password last re-entered (dangerous actions for REAUTH_TTL).
    mfa_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reauth_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A pending code sent by the Telegram bot, and failed attempts (lockout).
    mfa_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mfa_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
