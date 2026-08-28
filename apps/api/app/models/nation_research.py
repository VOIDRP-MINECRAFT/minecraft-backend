from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.nation import Nation


class NationResearch(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """Purchased level of a single research node for a nation (the tech tree).

    The node catalog itself is code-defined in
    :mod:`apps.api.app.services.nation_research_catalog`; this table only stores
    the per-nation owned level for each ``research_key``.
    """

    __tablename__ = "nation_research"
    __table_args__ = (
        UniqueConstraint("nation_id", "research_key", name="uq_nation_research_nation_id"),
    )

    nation_id: Mapped[UUID] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    research_key: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    nation: Mapped["Nation"] = relationship()
