"""Per-server tunables for the Void Upgrader (RTP, VC↔coin rate, limits).

One row per server; absent ⇒ the code defaults in ``void_upgrader_service`` apply.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class VoidUpgraderSettings(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "void_upgrader_settings"
    __table_args__ = (
        UniqueConstraint("server_id", name="uq_void_upgrader_settings_server"),
    )

    rtp: Mapped[float] = mapped_column(Float, nullable=False, default=0.90)          # return-to-player
    coins_per_vc: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)  # 1 VC = N coins (seed/import)
    min_stake: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    max_chance: Mapped[float] = mapped_column(Float, nullable=False, default=0.90)    # win-chance ceiling

    # Server-wide jackpot: a cut of every paid stake feeds a shared pot with a tiny per-spin hit chance.
    jackpot_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    jackpot_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)      # share of stake → pot
    jackpot_chance: Mapped[float] = mapped_column(Float, nullable=False, default=0.001)   # per-spin scoop chance
    jackpot_seed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=500)    # floor after a win

    # Daily free spin: house-paid stake once per day (must target a reward worth more than the free stake).
    daily_free_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    daily_free_stake: Mapped[int] = mapped_column(Integer, nullable=False, default=25)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
