from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class Bounty(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A single reward pledged (in diamonds) for killing ``target``. Placements
    stack: many open bounties on the same target are all claimed together when the
    target is killed, and their amounts summed for the killer's payout.

    ``status`` is ``open`` until the target is killed (``claimed``). Diamonds are
    held physically by the mod (removed from the placer on placement, given to the
    killer on claim); the backend only tracks the pledged amount."""

    __tablename__ = "bounties"
    __table_args__ = (
        Index("ix_bounties_server_target_status", "server_id", "target_nick_normalized", "status"),
    )

    target_nick: Mapped[str] = mapped_column(String(16), nullable=False)
    target_nick_normalized: Mapped[str] = mapped_column(String(16), nullable=False)
    target_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    placed_by_nick: Mapped[str] = mapped_column(String(16), nullable=False)
    placed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    killer_nick: Mapped[str | None] = mapped_column(String(16), nullable=True)
    killer_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    target_user: Mapped["User | None"] = relationship("User", foreign_keys=[target_user_id])
    placed_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[placed_by_user_id])
    killer_user: Mapped["User | None"] = relationship("User", foreign_keys=[killer_user_id])
