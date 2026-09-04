"""Battle Pass seasons (admin-managed, per server).

Each season has a stable ``season_key`` (the plugin's storage key — changing it resets
progress, so it never changes once created), a display name, start/end dates, a level cap,
and an ``is_active`` flag (exactly one active season per server). The plugin fetches the
active season from the backend and configures itself from it, falling back to config.yml.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class BattlePassSeason(UuidPrimaryKeyMixin, Base):
    __tablename__ = "battlepass_seasons"
    __table_args__ = (
        UniqueConstraint("server_id", "season_key", name="uq_battlepass_seasons_key"),
    )

    server_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season_key: Mapped[str] = mapped_column(String(32), nullable=False)   # stable storage key
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
