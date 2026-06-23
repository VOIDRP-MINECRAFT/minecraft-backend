from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class ReferralLink(UuidPrimaryKeyMixin, Base):
    __tablename__ = "referral_links"
    __table_args__ = (
        UniqueConstraint("invited_user_id", name="uq_referral_links_invited_user_id"),
    )

    inviter_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invited_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    referral_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    inviter: Mapped["User"] = relationship(back_populates="referrals_sent", foreign_keys=[inviter_user_id])
    invited: Mapped["User"] = relationship(back_populates="referral_received", foreign_keys=[invited_user_id])