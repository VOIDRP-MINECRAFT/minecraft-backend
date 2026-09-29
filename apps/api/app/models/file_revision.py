"""Every save of a server file through the admin panel's file manager: the text before
and after, who saved it and when — for the file's history and for putting it back."""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


class FileRevision(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "file_revisions"

    # Relative to the server's folder, with forward slashes.
    path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    # None: the file did not exist before this save.
    content_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_after: Mapped[str] = mapped_column(Text, nullable=False)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    author: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A note from the one who saved it, or what the save was (e.g. "откат к версии от …").
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
