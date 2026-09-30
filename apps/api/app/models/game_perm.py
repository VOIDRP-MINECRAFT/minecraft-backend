"""In-game permissions (LuckPerms) managed from the admin panel — see core/game_perms.py."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class GamePermCatalog(Base):
    """What the VoidRpPerms plugin last reported: groups (nodes, members) and permissions."""

    __tablename__ = "game_perm_catalogs"

    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    plugin_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GamePermOp(UuidPrimaryKeyMixin, Base):
    """A change for the plugin to make in LuckPerms (pending → done / failed)."""

    __tablename__ = "game_perm_ops"

    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    op: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class _UserGroup:
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    group_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GamePermDirect(_UserGroup, Base):
    """A group given to a person directly in the panel (not through a role)."""

    __tablename__ = "game_perm_direct"


class GamePermApplied(_UserGroup, Base):
    """What the panel has put on a person in LuckPerms — only these it takes away."""

    __tablename__ = "game_perm_applied"


class GamePermFlag(Base):
    __tablename__ = "game_perm_flags"

    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True)
    group_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
