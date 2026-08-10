from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NewsCategory = Literal["update", "media"]


class NewsPostBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body: str = Field(default="", max_length=40000)
    cover_image_url: str | None = Field(default=None, max_length=512)


class NewsPostCreate(NewsPostBase):
    category: NewsCategory = "update"
    is_published: bool = True
    # Auto-broadcast on create/publish.
    post_telegram: bool = False
    post_discord: bool = False


class NewsPostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=40000)
    cover_image_url: str | None = Field(default=None, max_length=512)
    is_published: bool | None = None


class NewsPostPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    title: str
    slug: str
    summary: str | None
    body: str
    cover_image_url: str | None
    published_at: datetime | None
    author_name: str | None


class NewsBroadcastResult(BaseModel):
    telegram_ok: bool | None = None
    discord_ok: bool | None = None
    detail: str | None = None


class NewsPostAdmin(NewsPostPublic):
    model_config = ConfigDict(from_attributes=True)

    server_id: str
    is_published: bool
    posted_telegram: bool
    posted_discord: bool
    created_at: datetime
    # Populated only on create when auto-broadcast was requested, so the
    # sender learns immediately if delivery to a channel failed.
    broadcast: NewsBroadcastResult | None = None


class NewsListResponse(BaseModel):
    items: list[NewsPostPublic]
    total: int


class NewsAdminListResponse(BaseModel):
    items: list[NewsPostAdmin]
    total: int


class NewsBroadcastRequest(BaseModel):
    """Re-send an existing post to channels."""

    post_telegram: bool = False
    post_discord: bool = False
