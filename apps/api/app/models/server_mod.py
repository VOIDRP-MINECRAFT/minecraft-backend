from __future__ import annotations

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)


class ServerModMeta(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """Admin-editable classification override for a single mod jar on a server.

    This table stores ONLY metadata (optional/required flags + display name and
    description), keyed by the jar's file name. Whether the mod is physically
    present on the client pack or the server mods dir is always derived by
    scanning those directories — never stored here — so the DB can't drift out
    of sync with the filesystem.

    The manifest generator reads these rows as an override that wins over its
    hardcoded classification dicts, so admin choices in the panel take effect on
    the next manifest rebuild. Absence of a row = fall back to the generator's
    built-in classification (backward compatible with the existing pack).
    """

    __tablename__ = "server_mod_meta"
    __table_args__ = (
        UniqueConstraint("server_id", "filename", name="uq_server_mod_meta_server_filename"),
    )

    # Jar file name only (basename, e.g. "journeymap-1.21.1-forge.jar").
    filename: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Client optional toggle: shown in the launcher's optional-mods list.
    optional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Locked-required optional: shown but can't be disabled by the player.
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
