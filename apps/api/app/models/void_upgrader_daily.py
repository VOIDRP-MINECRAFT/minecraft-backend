"""Per-player daily-free-spin ledger for the Void Upgrader.

One row per (server, player). ``last_free_spin_date`` gates the once-a-day free spin;
``streak`` counts consecutive days the player claimed it (resets when a day is skipped).
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class VoidUpgraderDaily(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "void_upgrader_daily"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_void_upgrader_daily_server_user"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    minecraft_nickname: Mapped[str] = mapped_column(String(48), nullable=False)
    last_free_spin_date: Mapped[date] = mapped_column(Date, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
