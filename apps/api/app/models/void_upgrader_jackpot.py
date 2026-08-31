"""Server-wide progressive jackpot for the Void Upgrader.

One row per server. A small cut of every paid spin's stake feeds ``amount``; each spin
has a tiny independent chance to scoop the whole pot, which then resets to the seed floor.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class VoidUpgraderJackpot(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "void_upgrader_jackpot"
    __table_args__ = (
        UniqueConstraint("server_id", name="uq_void_upgrader_jackpot_server"),
    )

    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)        # current pot (VC)
    last_winner_nickname: Mapped[str | None] = mapped_column(String(48), nullable=True)
    last_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)        # size of the last scoop
    last_won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
