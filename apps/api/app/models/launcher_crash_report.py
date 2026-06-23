from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class LauncherCrashReport(UuidPrimaryKeyMixin, Base):
    __tablename__ = "launcher_crash_reports"

    player_nickname: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    crash_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
