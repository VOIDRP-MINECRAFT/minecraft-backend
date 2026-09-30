"""A published build of one of our plugins or mods, for the «Интеграция» page."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class PluginRelease(UuidPrimaryKeyMixin, Base):
    __tablename__ = "plugin_releases"
    __table_args__ = (UniqueConstraint("plugin", "version", "filename", name="uq_plugin_releases_plugin_version_file"),)

    # Key from core/integration_catalog.py: "voidrp-auth", "voidrp-perms", …
    plugin: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    # ["paper", "folia"] / ["neoforge", "hybrid"]
    platforms: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    mc_versions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the partner saves the file as (a mod may have one build per Minecraft version).
    filename: Mapped[str] = mapped_column(String(160), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    published_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
