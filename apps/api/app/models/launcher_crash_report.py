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
    # Tail of the game's logs/latest.log — present even when no crash-report file
    # was written (OOM, hard native crash), which is the common case.
    log_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    launcher_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    os_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    java_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ram_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    server_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
