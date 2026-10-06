"""Second-day return (core/retention.py): deliveries to players in game and Telegram reminders."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base


class RetentionDelivery(Base):
    """A welcome message or a second-day reward to give a player in game: commands run through
    the server console (RCON on our servers, the VoidRpPerms queue on partners')."""

    __tablename__ = "retention_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    nickname: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deliver_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlayerReminder(Base):
    """A Telegram reminder sent once (kind ``day2``), or the player's «не напоминать» (``optout``)."""

    __tablename__ = "player_reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    server_id: Mapped[UUID | None] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlayerLoginDay(Base):
    """A day (Moscow) a player logged in to a server — login streaks, funnel return days."""

    __tablename__ = "player_login_days"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)


class LauncherDownload(Base):
    """A click on «Скачать лаунчер» on the site (the account, when signed in) — for the funnel."""

    __tablename__ = "launcher_downloads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
