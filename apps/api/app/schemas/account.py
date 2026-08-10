from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from apps.api.app.schemas.common import ORMModel


class PlayerAccountRead(ORMModel):
    id: UUID
    minecraft_nickname: str
    nickname_locked: bool
    legacy_auth_enabled: bool


class UserRead(ORMModel):
    id: UUID
    site_login: str
    email: str
    email_verified: bool
    is_active: bool
    is_admin: bool
    is_moderator: bool = False
    # Granted moderator permission keys (empty for full admins — the frontend
    # applies an is_admin bypass). Reads from the ORM ``staff_permissions`` column.
    permissions: list[str] = Field(default_factory=list, validation_alias="staff_permissions")
    created_at: datetime


class AccountSecurityRead(ORMModel):
    active_refresh_sessions: int
    must_use_launcher: bool
    legacy_hash_present: bool
    legacy_ready: bool


class MeResponse(ORMModel):
    user: UserRead
    player_account: PlayerAccountRead
    security: AccountSecurityRead


class RevokeOtherSessionsRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class RevokeSessionsResponse(ORMModel):
    message: str
    revoked_sessions: int




class PlayerSkinRead(ORMModel):
    has_skin: bool = False
    model_variant: str = "classic"
    skin_url: str | None = None
    head_preview_url: str | None = None
    body_preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    updated_at: datetime | None = None


class AccountSkinResponse(ORMModel):
    message: str
    skin: PlayerSkinRead
