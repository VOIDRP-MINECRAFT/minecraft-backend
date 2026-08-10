from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class TelegramLinkToken(UuidPrimaryKeyMixin, Base):
    """One-time nonce issued by the bot; consumed by the site to bind a Telegram
    account to a VoidRP :class:`User`. Written by the bot, read by the API."""

    __tablename__ = "telegram_link_tokens"

    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramGameChat(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Chat (+optional forum topic) where bot mini-games are allowed. Managed by
    staff with ``telegram.games.manage`` via the bot."""

    __tablename__ = "telegram_game_chats"
    __table_args__ = (UniqueConstraint("chat_id", "thread_id", name="uq_telegram_game_chats_chat_thread"),)

    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    thread_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    added_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TelegramGameScore(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Per-chat mini-game score ("войды") for a Telegram user."""

    __tablename__ = "telegram_game_scores"
    __table_args__ = (
        UniqueConstraint("telegram_user_id", "chat_id", name="uq_telegram_game_scores_user_chat"),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_daily_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
