from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)


class BattlePassPremium(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "battlepass_premium"
    __table_args__ = (
        UniqueConstraint("server_id", "minecraft_uuid", name="uq_battlepass_premium_server_uuid"),
    )

    minecraft_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    minecraft_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class BattlePassProgress(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "battlepass_progress"
    __table_args__ = (
        UniqueConstraint("server_id", "minecraft_uuid", name="uq_battlepass_progress_server_uuid"),
    )

    minecraft_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    minecraft_nickname: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
