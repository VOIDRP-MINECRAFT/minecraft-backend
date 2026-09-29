"""Changes to a server's mods and plugins that wait for the server to be stopped, and
the jobs that restart a server to apply them.

A jar is never put over, removed from or moved away from a running server: the JVM
still reads the old file and fails later, out of the blue. So such a change is queued
here and applied while the server is down — right away if it already is, by the worker
whenever it finds it stopped, or by a restart job ("Перезапустить и применить").
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


class ServerFileChange(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "server_file_changes"

    # "mod" (server mods/) or "plugin" (plugins/).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # add (a new jar, or a new version when ``replaces`` is set) | remove | disable | enable
    op: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # The staged jar to put in place, for "add".
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # The jar a new version takes the place of.
    replaces: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # What it is, for people: "LuckPerms 5.4.1 → 5.4.2".
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ServerRestartJob(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """"Перезапустить и применить": warn, stop, apply the queued changes in the gap
    before systemd starts the server again, wait until it answers."""
    __tablename__ = "server_restart_jobs"

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    step: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warn_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
