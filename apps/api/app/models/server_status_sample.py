"""A five-minute snapshot of a game server: up or not, players, TPS — for uptime and charts."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base


class ServerStatusSample(Base):
    __tablename__ = "server_status_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # The required modules answered (a partner's server), or any of our plugins did (ours).
    up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    online: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_players: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    mspt: Mapped[float | None] = mapped_column(Float, nullable=True)
