"""Banned items, per server — see routes/admin_item_bans.py and docs/item_bans_plan.md.

The list lives here and is edited in the admin panel; the game server's plugin fetches it
by its secret and removes those items from players. ``server_items`` holds what the plugin
reports about the server: every item id it has (the admin search shows only those) and when
it last took the list (so the page can tell whether bans actually work there).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin

DEFAULT_ITEM_BAN_SETTINGS: dict[str, Any] = {
    "message": "§c⛔ Этот предмет запрещён на сервере и был удалён из инвентаря.",
    "scan_period_ticks": 100,
}
# A full inventory sweep more often than every 2 s costs TPS for nothing; rarer than a
# minute lets a banned item be used for too long.
SCAN_PERIOD_BOUNDS = (40, 1200)
MESSAGE_MAX = 256


def resolve_item_ban_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Stored settings over the defaults, clamped — missing keys fall back to defaults."""
    out = dict(DEFAULT_ITEM_BAN_SETTINGS)
    raw = raw or {}
    message = raw.get("message")
    if isinstance(message, str) and message.strip():
        out["message"] = message.strip()[:MESSAGE_MAX]
    period = raw.get("scan_period_ticks")
    if isinstance(period, int) and not isinstance(period, bool):
        lo, hi = SCAN_PERIOD_BOUNDS
        out["scan_period_ticks"] = max(lo, min(hi, period))
    return out


class BannedItem(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "banned_items"
    __table_args__ = (UniqueConstraint("server_id", "item_id", name="uq_banned_items_server_item"),)

    # namespaced id, lowercase: "reliquary:rod_of_lyssa"
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Why it is banned — for staff, shown in the list.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Off = kept in the list for the record, but the server lets the item be.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ServerItems(Base):
    """What a server's plugin reported: its item registry and when it last took the list."""

    __tablename__ = "server_items"

    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True)
    item_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    items_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bans_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plugin_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
