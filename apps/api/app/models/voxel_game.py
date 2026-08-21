from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)


class VoxelGame(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A Voxel Engine game definition, authored on the platform and pulled by
    the in-game mod over the two-way channel.

    ``definition`` is the full flat game JSON (format / id / name / zones /
    triggers) — the same contract the mod's ``GameLoader`` reads. ``version``
    bumps on every edit so the mod can detect changes and hot-reload. The mod
    reports back load results into the ``last_report_*`` columns (bidirectional
    channel: loaded / failed / which line).
    """

    __tablename__ = "voxel_games"
    __table_args__ = (
        UniqueConstraint("server_id", "game_id", name="uq_voxel_games_server_game_id"),
    )

    # game_id is the per-server slug of the game (e.g. "arena_demo").
    game_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Bumped on every definition edit; the mod compares it to decide reload.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # enabled → the mod pulls it; is_active → the dispatcher runs it (≤1 per server).
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Reverse channel: last load result reported by the mod ──
    last_report_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok | error
    last_report_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reported_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
