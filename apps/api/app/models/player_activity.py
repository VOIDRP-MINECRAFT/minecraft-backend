from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin

# How a player reached the game that time.
CLIENT_LAUNCHER = "launcher"
CLIENT_EXTERNAL = "external"


class PlayerServerActivity(UuidPrimaryKeyMixin, Base):
    """One row per player per server: where they play and what they play from.

    Written on every successful login — by the play-ticket flow for launcher players and
    by the login plugin for everyone else — so the admin panel can answer "which servers
    is this account on, and does it come through our launcher or some other client"
    without scanning ticket history.
    """

    __tablename__ = "player_server_activity"
    __table_args__ = (UniqueConstraint("user_id", "server_id", name="uq_player_server_activity"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    server_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Which client was used last, and how often each kind has been used.
    last_client: Mapped[str] = mapped_column(String(16), nullable=False)
    launcher_logins: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    external_logins: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
