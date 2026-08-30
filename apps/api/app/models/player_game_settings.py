from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class PlayerGameSettings(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    """Account-level in-game (webgui) settings that sync across sessions and drive server
    behavior. One row per (server, user). ``settings`` JSON keys:
      - ``hud_auto_open`` (bool, default true): open the HUD overlay on join.
      - ``muted_notifications`` (list[str]): notification ``type`` values the player opted out of.
    """

    __tablename__ = "player_game_settings"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_player_game_settings_server_user"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
