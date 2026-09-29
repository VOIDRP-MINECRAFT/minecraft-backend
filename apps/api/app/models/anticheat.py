from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


class AnticheatViolation(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "anticheat_violations"

    player_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    player_nick: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actual_value: Mapped[float] = mapped_column(nullable=False, default=0.0)
    expected_max: Mapped[float] = mapped_column(nullable=False, default=0.0)
    vl: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default="LOW")

    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AnticheatModSnapshot(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "anticheat_mod_snapshots"

    player_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    player_nick: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mods: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    suspicious_mods: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    resource_pack_status: Mapped[str] = mapped_column(String(16), nullable=False, default="NONE")


class ModVerdict(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Admin verdict for a specific mod ID — CHEAT or SAFE."""
    __tablename__ = "mod_verdicts"
    __table_args__ = (UniqueConstraint("mod_id", name="uq_mod_verdicts_mod_id"),)

    mod_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)   # CHEAT | SAFE
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnticheatInjectionReport(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """Client-side injection detection report (agents, native libs)."""
    __tablename__ = "anticheat_injection_reports"

    player_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    player_nick: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    java_agents: Mapped[str] = mapped_column(Text, nullable=False, default="[]")       # JSON list
    suspicious_libraries: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    agents_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AnticheatThresholdConfig(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Admin-editable check thresholds, synced to the game server mod or plugin.

    A row without a server is the value every server gets; a row with one overrides it
    for that server alone. One of each per key.
    """
    __tablename__ = "anticheat_threshold_configs"
    __table_args__ = (
        Index("uq_anticheat_threshold_configs_key_global", "key", unique=True,
              postgresql_where=text("server_id IS NULL")),
        Index("uq_anticheat_threshold_configs_key_server", "key", "server_id", unique=True,
              postgresql_where=text("server_id IS NOT NULL")),
    )

    server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    min_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_value: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    step: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AnticheatAction(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """Something staff asked the game server to do, which its plugin picks up and runs.

    ``kind`` is ``rollback`` or ``restore`` (undo a rollback), carried out through
    CoreProtect; ``params`` holds what it needs — the player, how far back, the radius
    and the place. The plugin moves it from ``pending`` through ``running`` to ``done``
    or ``failed`` and writes what happened into ``result``.
    """
    __tablename__ = "anticheat_actions"

    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_nick: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
