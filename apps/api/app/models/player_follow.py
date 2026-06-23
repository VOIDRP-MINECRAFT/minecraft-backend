from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class PlayerFollow(UuidPrimaryKeyMixin, Base):
    __tablename__ = "player_follows"
    __table_args__ = (
        UniqueConstraint("follower_user_id", "target_user_id", name="uq_player_follows_pair"),
        CheckConstraint("follower_user_id <> target_user_id", name="ck_player_follows_no_self"),
    )

    follower_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    follower: Mapped["User"] = relationship(back_populates="following_links", foreign_keys=[follower_user_id])
    target: Mapped["User"] = relationship(back_populates="follower_links", foreign_keys=[target_user_id])