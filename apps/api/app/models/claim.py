from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class Claim(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A block-anchored land claim. ``level`` drives the protected chunk radius:
    level L protects a (2L-1)x(2L-1) chunk square centred on the core chunk."""

    __tablename__ = "claims"

    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    core_x: Mapped[int] = mapped_column(Integer, nullable=False)
    core_y: Mapped[int] = mapped_column(Integer, nullable=False)
    core_z: Mapped[int] = mapped_column(Integer, nullable=False)
    core_chunk_x: Mapped[int] = mapped_column(Integer, nullable=False)
    core_chunk_z: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Set of 16x16x16 cube cells [[cx, cy, cz], ...] making up the claim volume.
    cubes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_user_id])
    trusted: Mapped[list["ClaimTrusted"]] = relationship(
        "ClaimTrusted",
        back_populates="claim",
        cascade="all, delete-orphan",
    )


class ClaimTrusted(UuidPrimaryKeyMixin, Base):
    __tablename__ = "claim_trusted"
    __table_args__ = (
        UniqueConstraint("claim_id", "user_id", name="uq_claim_trusted_claim_user"),
    )

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Join table — only created_at (matches the migration; no updated_at column).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="trusted")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
