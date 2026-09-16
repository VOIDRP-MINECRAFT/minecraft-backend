from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from apps.api.app.schemas.account import PlayerAccountRead, UserRead

PROFILE_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
ACCENT_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Platform -> hosts a link for it may point to. Anything else is rejected, so a
# profile can't be used to park phishing links under a "YouTube" icon.
SOCIAL_LINK_HOSTS: dict[str, tuple[str, ...]] = {
    "twitch": ("twitch.tv",),
    "youtube": ("youtube.com", "youtu.be"),
    "telegram": ("t.me", "telegram.me"),
    "discord": ("discord.gg", "discord.com"),
    "vk": ("vk.com", "vk.ru"),
    "tiktok": ("tiktok.com",),
}
SOCIAL_LINK_MAX_LENGTH = 200


def normalize_social_links(value: dict[str, str | None] | None) -> dict[str, str]:
    """Validate a {platform: url} map; empty/None values drop the platform."""
    from urllib.parse import urlsplit

    if value is None:
        return {}
    result: dict[str, str] = {}
    for platform, raw in value.items():
        if platform not in SOCIAL_LINK_HOSTS:
            raise ValueError(f"unknown social link platform: {platform}")
        url = (raw or "").strip()
        if not url:
            continue
        if len(url) > SOCIAL_LINK_MAX_LENGTH:
            raise ValueError(f"{platform} link is too long")
        if "://" not in url:
            url = "https://" + url
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        allowed = SOCIAL_LINK_HOSTS[platform]
        if parts.scheme not in ("http", "https") or not any(
            host == h or host.endswith("." + h) for h in allowed
        ):
            raise ValueError(f"{platform} link must point to {', '.join(allowed)}")
        if not parts.path.strip("/"):
            raise ValueError(f"{platform} link must lead to a channel or profile")
        result[platform] = "https://" + (parts.netloc.lower()) + parts.path + (f"?{parts.query}" if parts.query else "")
    return result


class PublicProfileAssetsRead(BaseModel):
    avatar_url: str | None = None
    avatar_preview_url: str | None = None
    banner_url: str | None = None
    banner_preview_url: str | None = None
    background_url: str | None = None
    background_preview_url: str | None = None


class PublicProfileNationSummaryRead(BaseModel):
    id: UUID
    slug: str
    title: str
    tag: str
    short_description: str | None = None
    accent_color: str | None = None
    icon_url: str | None = None
    icon_preview_url: str | None = None


class PublicProfileStatsRead(BaseModel):
    followers: int
    following: int
    friends: int
    pending_referrals: int
    qualified_referrals: int


class PublicProfileViewerStateRead(BaseModel):
    is_self: bool
    is_following: bool
    follows_you: bool
    is_friend: bool


class PublicProfileRead(BaseModel):
    user: UserRead
    player_account: PlayerAccountRead
    slug: str
    display_name: str | None = None
    bio: str | None = None
    status_text: str | None = None
    theme_mode: str
    accent_color: str | None = None
    social_links: dict[str, str] = Field(default_factory=dict)
    is_public: bool
    allow_followers_list_public: bool
    allow_friends_list_public: bool
    assets: PublicProfileAssetsRead
    nation: PublicProfileNationSummaryRead | None = None
    stats: PublicProfileStatsRead
    viewer: PublicProfileViewerStateRead
    current_referral_rank: str | None = None
    current_referral_rank_expires_at: datetime | None = None


class PublicUserSummaryRead(BaseModel):
    """What anyone may see about a profile's owner: no email, id, roles or permissions."""
    site_login: str
    created_at: datetime


class PublicPlayerAccountSummaryRead(BaseModel):
    minecraft_nickname: str


class PublicProfileViewRead(PublicProfileRead):
    """``GET /profiles/{slug}`` — the page is public, so the owner's account is trimmed."""
    user: PublicUserSummaryRead
    player_account: PublicPlayerAccountSummaryRead


class UpdatePublicProfileRequest(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=500)
    status_text: str | None = Field(default=None, max_length=140)
    theme_mode: str | None = Field(default=None, max_length=32)
    accent_color: str | None = Field(default=None, max_length=7)
    social_links: dict[str, str | None] | None = None
    is_public: bool | None = None
    allow_followers_list_public: bool | None = None
    allow_friends_list_public: bool | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not PROFILE_SLUG_PATTERN.fullmatch(value):
            raise ValueError("slug must match ^[a-z0-9][a-z0-9._-]{2,63}$")
        return value

    @field_validator("social_links")
    @classmethod
    def validate_social_links(cls, value: dict[str, str | None] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return normalize_social_links(value)

    @field_validator("accent_color")
    @classmethod
    def validate_accent_color(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        value = value.strip()
        if not ACCENT_COLOR_PATTERN.fullmatch(value):
            raise ValueError("accent_color must be like #A1B2C3")
        return value

    @field_validator("display_name", "bio", "status_text", "theme_mode")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ProfileAssetUploadResponse(BaseModel):
    message: str
    profile: PublicProfileRead


class DeleteProfileAssetResponse(BaseModel):
    message: str
    profile: PublicProfileRead
