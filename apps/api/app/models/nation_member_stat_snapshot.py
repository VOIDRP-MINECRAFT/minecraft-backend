from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.nation import Nation
    from apps.api.app.models.user import User


class NationMemberStatSnapshot(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "nation_member_stat_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "nation_id",
            "minecraft_nickname_normalized",
            name="uq_nation_member_stat_snapshots_nation_nickname",
        ),
    )

    nation_id: Mapped[UUID] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    minecraft_nickname: Mapped[str] = mapped_column(String(16), nullable=False)
    minecraft_nickname_normalized: Mapped[str] = mapped_column(String(16), nullable=False)

    total_playtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pvp_kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mob_kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocks_placed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    blocks_broken: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    current_balance: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    completed_quests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="cached")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=func.now,
        index=True,
    )

    nation: Mapped["Nation"] = relationship("Nation")
    user: Mapped["User | None"] = relationship("User")


