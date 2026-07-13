from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    UuidPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class KillEvent(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    """A single PvP kill on an anarchy server, for the public killfeed. Stores only
    who killed whom + the weapon — never coordinates — so it is safe on anarchy.
    ``kind`` is extensible (``pvp`` now; ``raid`` etc. later). Append-only log."""

    __tablename__ = "kill_events"
    __table_args__ = (
        Index("ix_kill_events_server_created", "server_id", "created_at"),
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="pvp")

    killer_nick: Mapped[str] = mapped_column(String(16), nullable=False)
    killer_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    victim_nick: Mapped[str] = mapped_column(String(16), nullable=False)
    victim_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Item id of the killer's weapon (e.g. "minecraft:netherite_sword") or null = fists.
    weapon: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    killer_user: Mapped["User | None"] = relationship("User", foreign_keys=[killer_user_id])
    victim_user: Mapped["User | None"] = relationship("User", foreign_keys=[victim_user_id])
