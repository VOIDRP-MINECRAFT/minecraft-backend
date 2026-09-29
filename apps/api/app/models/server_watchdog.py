"""The per-server watchdog: its settings and what it last saw (one row per server), and
what it did or noticed (events). The checking itself is ``apps/worker/watchdog.py``."""
from __future__ import annotations

from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


def default_watchdog() -> dict[str, Any]:
    # On/off is not here: it is the Monitoring card's "Сторож зависаний" switch
    # (voidrp-watchdog.json in the server's folder).
    return {
        # Minutes the server may not answer before it counts as hung.
        "hang_minutes": 3,
        # Minutes after a start during which it is left alone to boot.
        "startup_grace_minutes": 5,
        # "restart" — kill the hung process, systemd starts it again; "notify" — only report.
        "action": "restart",
        "max_restarts_per_hour": 3,
        # The server has a watchdog script of its own (the main server's
        # minecraft_watchdog.sh / hang_guard.sh): this one then leaves it alone, as two
        # watchdogs acting on one server would fight.
        "own_script": False,
    }


class ServerWatchdog(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "server_watchdogs"
    __table_args__ = (UniqueConstraint("server_id", name="uq_server_watchdogs_server"),)

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=default_watchdog)
    # What the worker saw last: status (ok | booting | unresponsive | down | maintenance |
    # restoring | off), since when it has been failing, the last check and answer time.
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ServerWatchdogEvent(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """``kind``: hang (noticed, not restarted), restart (killed a hung server), down (the
    unit is not running), recovered (answering again), limit (hung, but the hourly limit of
    restarts was reached)."""
    __tablename__ = "server_watchdog_events"

    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dump_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
