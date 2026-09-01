"""Cosmetics catalog + ownership for the Figura system.

A catalog entry points at a stored Figura avatar (owner = COSMETIC_OWNER, avatar_id = slug).
Players buy a cosmetic with Void Coins → own it → may equip it. Slots are stored for the
future per-player compositor; v1 equips one cosmetic as the whole avatar.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class FiguraCosmetic(UuidPrimaryKeyMixin, Base):
    __tablename__ = "figura_cosmetics"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_figura_cosmetics_slug"),
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False)          # == avatar_id under COSMETIC_OWNER
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    slot: Mapped[str] = mapped_column(String(24), nullable=False, default="full")   # full/head/body/wings/…
    price_void_coins: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FiguraCosmeticOwned(UuidPrimaryKeyMixin, Base):
    __tablename__ = "figura_cosmetic_owned"
    __table_args__ = (
        UniqueConstraint("user_id", "cosmetic_slug", name="uq_figura_cosmetic_owned"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    cosmetic_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
