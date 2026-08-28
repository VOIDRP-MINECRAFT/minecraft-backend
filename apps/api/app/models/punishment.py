from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin

# Punishment kinds. Temp variants carry an ``expires_at``; permanent ones don't.
PUNISHMENT_TYPES = ("ban", "tempban", "mute", "tempmute", "kick", "warn")
# Kinds that keep a standing state until they expire or are revoked. ``kick``
# and ``warn`` are point-in-time events and are stored inactive from the start.
STANDING_TYPES = ("ban", "tempban", "mute", "tempmute")


class Punishment(UuidPrimaryKeyMixin, Base):
    """A moderation action against a player — the central ban/mute ledger.

    ``server_id`` is nullable: null means a platform-wide punishment, otherwise
    it is scoped to one game server. ``active`` reflects the standing state; a
    background/query-time check compares ``expires_at`` to now for temp types.
    """

    __tablename__ = "punishments"

    server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True, index=True
    )

    player_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    player_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    issued_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issued_by_name: Mapped[str] = mapped_column(String(120), nullable=False, default="system")

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        now = datetime.now(self.expires_at.tzinfo)
        return now >= self.expires_at

    @property
    def is_effective(self) -> bool:
        """Currently in force: standing type, still active, not past expiry."""
        return self.active and self.type in STANDING_TYPES and not self.is_expired
