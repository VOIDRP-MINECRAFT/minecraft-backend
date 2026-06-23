from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class LegacyLoginRequest(BaseModel):
    player_name: str = Field(min_length=3, max_length=16)
    password: str = Field(min_length=1, max_length=256)


class LegacyLoginResponse(BaseModel):
    accepted: bool = True
    user_id: UUID
    minecraft_nickname: str
    legacy_auth_enabled: bool
    email_verified: bool


class PlayerAccessRequest(BaseModel):
    player_name: str


class PlayerAccessResponse(BaseModel):
    player_exists: bool
    user_active: bool
    legacy_auth_enabled: bool
    must_use_launcher: bool
    minecraft_nickname: str | None = None
    error: str | None = None


class PlayerSkinResponse(BaseModel):
    player_exists: bool = True
    has_skin: bool = False
    model_variant: str = "classic"
    skin_url: str | None = None
    head_preview_url: str | None = None
    body_preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    updated_at: str | None = None
