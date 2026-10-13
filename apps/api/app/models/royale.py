"""Royale (battle royale) matches: what the VoidRpRoyale plugin sends after each game.

Kept apart from the server row on purpose — ``server_id`` goes to NULL when the server is
deleted and ``server_slug`` stays — because the tournament server is temporary and its
results are handed to the Academy's teaching staff afterwards.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class RoyaleMatch(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "royale_matches"

    server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_servers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    server_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    match_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    map: Mapped[str] = mapped_column(String(64), nullable=False)
    map_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aborted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    winner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    winner_title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    teams_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    players_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The whole payload as the plugin sent it: teams, players with every counter, events.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
