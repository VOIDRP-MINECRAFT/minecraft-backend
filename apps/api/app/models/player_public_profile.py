from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.media_asset import MediaAsset
    from apps.api.app.models.user import User


class PlayerPublicProfile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_public_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_text: Mapped[str | None] = mapped_column(String(140), nullable=True)

    theme_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    accent_color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    avatar_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    banner_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    background_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_followers_list_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_friends_list_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_profile_comments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship(back_populates="public_profile")

    avatar_asset: Mapped["MediaAsset | None"] = relationship(foreign_keys=[avatar_asset_id], lazy="joined")
    banner_asset: Mapped["MediaAsset | None"] = relationship(foreign_keys=[banner_asset_id], lazy="joined")
    background_asset: Mapped["MediaAsset | None"] = relationship(foreign_keys=[background_asset_id], lazy="joined")