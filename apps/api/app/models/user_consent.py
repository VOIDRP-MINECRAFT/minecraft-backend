"""Append-only log of the consents a user gave or withdrew.

Each row is one action: which document and edition, granted or not, the chosen categories for the
distribution consent, and where it came from. The current state is the latest row per document.
Kept as evidence of consent (152-FZ requires the operator to be able to prove it).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class UserConsent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "user_consents"
    __table_args__ = (Index("ix_user_consents_user_document", "user_id", "document", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
