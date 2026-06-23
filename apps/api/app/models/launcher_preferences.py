from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.user import User


class LauncherPreferences(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "launcher_preferences"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    disabled_mods_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="'[]'"
    )
    config_files_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="'{}'"
    )

    user: Mapped["User"] = relationship()
