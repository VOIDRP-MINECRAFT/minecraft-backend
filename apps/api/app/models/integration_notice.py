"""What was announced to whom about a server's integration — every notice goes out once."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class IntegrationNotice(UuidPrimaryKeyMixin, Base):
    __tablename__ = "integration_notices"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", "kind", "ref", name="uq_integration_notices_once"),
    )

    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # "release" (ref: release id) | "module_down" / "module_up" (ref: module + since) | "secret" (ref: time)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ref: Mapped[str] = mapped_column(String(128), nullable=False)
    telegram_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
