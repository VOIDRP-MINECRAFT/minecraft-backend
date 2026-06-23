from __future__ import annotations

from pydantic import BaseModel


class SocialProfileCard(BaseModel):
    slug: str
    site_login: str
    minecraft_nickname: str
    display_name: str | None = None
    avatar_url: str | None = None
    is_friend: bool = False


class FollowActionResponse(BaseModel):
    message: str
    is_following: bool
    is_friend: bool


class SocialListResponse(BaseModel):
    total: int
    items: list[SocialProfileCard]