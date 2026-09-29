"""Pay for playing: money for every so many minutes of active play, up to a daily cap.

The game server's plugin counts the active minutes and asks for each payout; the
backend decides — whether it is on, how much, and whether the player's cap for the day
(Moscow time) still allows it — and keeps every payout for the admin panel.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


def default_playtime_pay() -> dict[str, Any]:
    return {"enabled": False, "amount": 50.0, "every_minutes": 30, "daily_cap": 300.0, "afk_minutes": 5}


class PlaytimePaySettings(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "playtime_pay_settings"
    __table_args__ = (UniqueConstraint("server_id", name="uq_playtime_pay_settings_server"),)

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=default_playtime_pay)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PlaytimePayout(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """One payout. ``claim_id`` comes from the plugin, so a retried request pays once."""
    __tablename__ = "playtime_payouts"
    __table_args__ = (
        UniqueConstraint("server_id", "claim_id", name="uq_playtime_payouts_claim"),
        Index("ix_playtime_payouts_server_day_player", "server_id", "day", "player_uuid"),
    )

    claim_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    player_name: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # The day it counts towards, in Moscow time — when the daily cap resets.
    day: Mapped[date] = mapped_column(Date, nullable=False)
