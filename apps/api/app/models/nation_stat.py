from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.nation import Nation


class NationStat(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nation_stats"
    __table_args__ = (
        UniqueConstraint("nation_id", name="uq_nation_stats_nation_id"),
    )

    nation_id: Mapped[UUID] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    treasury_balance: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    territory_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_playtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pvp_kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mob_kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    boss_kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocks_placed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    blocks_broken: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    events_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prestige_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    nation: Mapped["Nation"] = relationship()
