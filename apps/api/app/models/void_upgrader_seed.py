"""Per-player active server seed for the Void Upgrader's commit-reveal fairness.

The SHA-256 of ``server_seed`` is published to the player BEFORE they spin (the commit);
every spin rolls from this seed with an incrementing ``nonce``. The raw seed is revealed
only when the player rotates it — at which point every past spin under it becomes
independently verifiable and a fresh seed is committed.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class VoidUpgraderSeed(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "void_upgrader_seed"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_void_upgrader_seed_server_user"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    server_seed: Mapped[str] = mapped_column(String(64), nullable=False)   # active secret (revealed on rotate)
    nonce: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # next spin's nonce under this seed
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
