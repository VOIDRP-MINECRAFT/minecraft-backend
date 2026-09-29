"""Backups of a game server's worlds, made and restored from the admin panel.

The API only records what staff ask for; ``apps/worker/backups.py`` (run from cron)
does the work — archiving the worlds, restoring one, pruning old scheduled ones — and
writes the outcome back here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


class ServerBackup(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """One archive of a server's worlds.

    ``kind``: ``manual`` (made by staff), ``scheduled`` (by the schedule; only these are
    pruned by the "keep" setting) or ``pre_restore`` (made right before a restore, so a
    restore can itself be undone). ``status`` goes ``pending`` → ``running`` → ``done`` or
    ``failed``; ``deleting`` while the worker removes the file.
    """
    __tablename__ = "server_backups"

    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Folder names archived (the server's world folders at the time).
    worlds: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ServerBackupRestore(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A request to put a server's worlds back to a backup.

    ``step`` says where the worker is (making the pre-restore backup, unpacking,
    stopping the server, swapping, waiting for it to come back) for the admin panel.
    """
    __tablename__ = "server_backup_restores"

    backup_id: Mapped[UUID] = mapped_column(ForeignKey("server_backups.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    step: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pre_backup_id: Mapped[UUID | None] = mapped_column(ForeignKey("server_backups.id", ondelete="SET NULL"), nullable=True)
    warn_seconds: Mapped[int] = mapped_column(nullable=False, default=30)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def default_backup_settings() -> dict[str, Any]:
    return {"enabled": False, "every_hours": 24, "keep": 7}


class ServerBackupSettings(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """The schedule of a server's backups: whether, how often, how many scheduled ones to keep."""
    __tablename__ = "server_backup_settings"
    __table_args__ = (UniqueConstraint("server_id", name="uq_server_backup_settings_server"),)

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=default_backup_settings)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
