from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class PlayerWeeklyChallenges(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    """Latest weekly-challenge state a player, pushed by the game-sync plugin.

    The plugin owns the tracking (per-week baselines) and reward delivery; it pushes the
    current week's 3 challenges here (key/title/goal/progress/reward/done) so the game-ui
    home can display them. One row per (server, player), overwritten each push.
    """

    __tablename__ = "player_weekly_challenges"
    __table_args__ = (
        UniqueConstraint("server_id", "minecraft_nickname_normalized", name="uq_weekly_challenges_server_nick"),
    )

    minecraft_nickname: Mapped[str] = mapped_column(String(48), nullable=False)
    minecraft_nickname_normalized: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    week_id: Mapped[str] = mapped_column(String(16), nullable=False)
    challenges: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
