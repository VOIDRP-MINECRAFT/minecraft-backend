from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class PlayerAccount(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_accounts"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    minecraft_nickname: Mapped[str] = mapped_column(String(16), nullable=False)
    minecraft_nickname_normalized: Mapped[str] = mapped_column(
        String(16), nullable=False, unique=True, index=True
    )

    # Premium currency (account-wide), bought via donation / granted by admins. Starts at 0.
    void_coins: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)

    nickname_locked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    legacy_auth_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    legacy_password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legacy_hash_algo: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship(back_populates="player_account")
