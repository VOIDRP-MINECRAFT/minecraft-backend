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
    # Launcher crash rule that recognized this crash (NULL = the player got generic advice).
    advice_rule_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class LauncherBootReport(UuidPrimaryKeyMixin, Base):
    """A launcher that could not start (its core never came up), sent without an account:
    when the launcher itself fails there is no session to report it with."""

    __tablename__ = "launcher_boot_reports"

    launcher_version: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    os_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # The error the player saw on the splash and the hint the launcher gave for it.
    error: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The same text the «Скопировать отчёт» button copies: core state, path, core log tail.
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tail of the Electron main-process log (startup steps, update check, core spawn).
    main_log_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
