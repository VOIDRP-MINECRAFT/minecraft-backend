"""Support policy of one of our plugins: the oldest version we still support."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base


class PluginSupport(Base):
    __tablename__ = "plugin_support"

    # Key from core/integration_catalog.py.
    plugin: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Below it a server must update: the page marks it red and the people running it hear once.
    min_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)
