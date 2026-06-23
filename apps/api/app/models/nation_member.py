from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.nation import Nation
    from apps.api.app.models.user import User


class NationMember(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nation_members"
    __table_args__ = (
        UniqueConstraint("nation_id", "user_id", name="uq_nation_members_nation_user"),
    )

    nation_id: Mapped[UUID] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    custom_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)

    nation: Mapped["Nation"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()
