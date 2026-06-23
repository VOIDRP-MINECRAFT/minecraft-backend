from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from apps.api.app.schemas.account import PlayerAccountRead, UserRead

PROFILE_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
ACCENT_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


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
    is_public: bool
    allow_followers_list_public: bool
    allow_friends_list_public: bool
    assets: PublicProfileAssetsRead
    nation: PublicProfileNationSummaryRead | None = None
    stats: PublicProfileStatsRead
    viewer: PublicProfileViewerStateRead
    current_referral_rank: str | None = None
    current_referral_rank_expires_at: datetime | None = None


class UpdatePublicProfileRequest(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=500)
    status_text: str | None = Field(default=None, max_length=140)
    theme_mode: str | None = Field(default=None, max_length=32)
    accent_color: str | None = Field(default=None, max_length=7)
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
