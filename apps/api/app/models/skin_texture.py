from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class SkinTexture(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A player skin signed by Mojang (through MineSkin), ready for a game profile.

    Offline-mode servers can only show a skin whose ``textures`` property carries Mojang's
    signature. A skin is signed once per picture and model and reused by every server.
    """

    __tablename__ = "skin_textures"
    __table_args__ = (
        UniqueConstraint("sha256", "model_variant", name="uq_skin_textures_sha_variant"),
    )

    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_variant: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    mineskin_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
