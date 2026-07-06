from __future__ import annotations

import enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class FeedbackType(str, enum.Enum):
    suggestion = "suggestion"
    bug = "bug"
    complaint = "complaint"


class PlayerFeedback(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_feedback"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which server this feedback was submitted from (nullable: global/legacy).
    server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_servers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[FeedbackType] = mapped_column(
        String(20), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
