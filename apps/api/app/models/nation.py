from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.nation_join_request import NationJoinRequest
    from apps.api.app.models.nation_member import NationMember
    from apps.api.app.models.user import User


class Nation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nations"

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    tag: Mapped[str] = mapped_column(String(8), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(140), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    accent_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    recruitment_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="request")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    leader_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    capital_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capital_z: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capital_world: Mapped[str | None] = mapped_column(String(64), nullable=True)

    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon_preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    banner_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    banner_preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    background_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    background_preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    leader: Mapped["User"] = relationship(foreign_keys=[leader_user_id])
    created_by: Mapped["User"] = relationship(foreign_keys=[created_by_user_id])

    members: Mapped[list["NationMember"]] = relationship(
        back_populates="nation",
        cascade="all, delete-orphan",
    )
    join_requests: Mapped[list["NationJoinRequest"]] = relationship(
        back_populates="nation",
        cascade="all, delete-orphan",
    )
