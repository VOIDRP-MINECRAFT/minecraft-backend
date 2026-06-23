from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class PlayerSkin(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_skins"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    model_variant: Mapped[str] = mapped_column(String(16), nullable=False, default="classic")
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False, default="image/png")
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    original_storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    original_url: Mapped[str] = mapped_column(String(512), nullable=False)

    head_preview_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    body_preview_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped["User"] = relationship(back_populates="player_skin")
