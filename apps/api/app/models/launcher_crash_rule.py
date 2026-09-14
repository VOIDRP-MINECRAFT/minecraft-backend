from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class LauncherCrashRule(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A crash-recognition rule the launcher downloads (GET /launcher/crash-rules).

    Same shape as the launcher's built-in rules (``core/launcher_crash_rules_builtin.json``):
    a rule with a built-in ``key`` replaces that built-in, ``enabled = False`` switches it off.
    ``server_id`` NULL = applies to every server; a server-specific rule wins over a global
    one with the same key.
    """

    __tablename__ = "launcher_crash_rules"

    server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # .NET-flavoured regexes (named groups written as (?<name>...)), matched case-insensitively.
    patterns_all: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    patterns_any: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    exit_codes: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    solution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # [{"type": "...", "label": "...", "paths": [...]}]
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
