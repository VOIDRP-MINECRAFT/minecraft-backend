from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class PlayerPlaytimeDaily(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    """Per-player playtime accumulated per calendar day, for the in-game activity chart.

    The game-sync plugin pushes each finished session's seconds (on quit); the backend
    adds them to the row for that day. Seconds are kept to avoid rounding loss; the API
    exposes minutes.
    """

    __tablename__ = "player_playtime_daily"
    __table_args__ = (
        UniqueConstraint("server_id", "minecraft_nickname_normalized", "day", name="uq_playtime_daily_server_nick_day"),
    )

    minecraft_nickname: Mapped[str] = mapped_column(String(48), nullable=False)
    minecraft_nickname_normalized: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
