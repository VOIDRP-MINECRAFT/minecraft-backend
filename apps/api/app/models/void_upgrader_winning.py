"""A won item held in the player's Upgrader inventory until they claim it in-game or
sell it back for Void Coins."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class VoidUpgraderWinning(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "void_upgrader_winnings"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    minecraft_nickname: Mapped[str] = mapped_column(String(48), nullable=False)
    item_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    vc_value: Mapped[int] = mapped_column(BigInteger, nullable=False)   # sell-back value in Void Coins
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tier: Mapped[str] = mapped_column(String(24), nullable=False, default="common")
    give_command: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
