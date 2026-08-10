from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)


class NewsPost(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A news post scoped to one game server.

    Body is stored as Markdown (authored in the admin panel). When published it
    can be auto-broadcast to the server's Telegram channel + Discord webhook.
    """

    __tablename__ = "news_posts"
    __table_args__ = (
        Index("ix_news_posts_server_published", "server_id", "is_published", "published_at"),
        Index("ix_news_posts_server_category_pub", "server_id", "category", "is_published", "published_at"),
    )

    # 'update' (patch notes) or 'media' (independent news). Each category has its
    # own TG/Discord channels (game_servers.news_channels) and permissions.
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="update")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Auto-broadcast tracking.
    posted_telegram: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    posted_discord: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
