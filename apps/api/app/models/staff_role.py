from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class StaffRole(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A named bundle of admin-panel permissions, like a Discord role.

    ``position``: higher = more senior; people with ``roles.manage`` / ``roles.assign``
    only touch roles below their own highest one. ``server_ids`` None → the role applies on
    every server (and may carry platform keys); a list of ``game_servers.id`` strings → only
    per-server keys, on those servers.
    """

    __tablename__ = "staff_roles"

    name: Mapped[str] = mapped_column(String(48), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#99aab5")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    server_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    permissions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A badge: a label about the person (like a fun Discord role) — never any permission,
    # no weight in seniority.
    is_badge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StaffRoleMember(Base):
    __tablename__ = "staff_role_members"

    role_id: Mapped[UUID] = mapped_column(ForeignKey("staff_roles.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
