from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class AnticheatViolation(UuidPrimaryKeyMixin, TimestampMixin, Base):
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


class AnticheatModSnapshot(UuidPrimaryKeyMixin, TimestampMixin, Base):
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


class AnticheatInjectionReport(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Client-side injection detection report (agents, native libs)."""
    __tablename__ = "anticheat_injection_reports"

    player_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    player_nick: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    java_agents: Mapped[str] = mapped_column(Text, nullable=False, default="[]")       # JSON list
    suspicious_libraries: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    agents_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AnticheatThresholdConfig(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Admin-editable check thresholds, synced to the game server mod."""
    __tablename__ = "anticheat_threshold_configs"
    __table_args__ = (UniqueConstraint("key", name="uq_anticheat_threshold_configs_key"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    min_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_value: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    step: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
