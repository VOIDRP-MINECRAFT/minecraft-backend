"""Self-hosted Figura backend storage.

Figura data is account-global (an avatar belongs to a Minecraft UUID, not a server).
See ``docs/figura_backend_spec.md`` for the reverse-engineered protocol.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class FiguraSession(UuidPrimaryKeyMixin, Base):
    """A Figura auth token issued to a player (maps token → uuid/name)."""
    __tablename__ = "figura_sessions"

    token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    minecraft_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    minecraft_nickname: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FiguraAvatar(UuidPrimaryKeyMixin, Base):
    """A stored Figura avatar blob (gzipped NBT) owned by a player."""
    __tablename__ = "figura_avatars"
    __table_args__ = (
        UniqueConstraint("owner_uuid", "avatar_id", name="uq_figura_avatars_owner_id"),
    )

    owner_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    avatar_id: Mapped[str] = mapped_column(String(64), nullable=False)   # the avatar "name"
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)      # hash the client dedupes on
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # cosmetic bookkeeping (server-authored cosmetics vs player uploads)
    is_cosmetic: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FiguraEquipped(UuidPrimaryKeyMixin, Base):
    """A player's currently-equipped avatar list (what everyone else renders)."""
    __tablename__ = "figura_equipped"
    __table_args__ = (
        UniqueConstraint("owner_uuid", name="uq_figura_equipped_owner"),
    )

    owner_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # list of {"owner": "<uuid>", "id": "<avatarId>"}
    equipped: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
