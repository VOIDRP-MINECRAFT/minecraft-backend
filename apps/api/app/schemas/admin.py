from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from apps.api.app.schemas.common import ORMModel


class AdminUserRead(ORMModel):
    id: UUID
    site_login: str
    email: str
    email_verified: bool
    is_active: bool
    created_at: datetime


class AdminPlayerAccountRead(ORMModel):
    id: UUID
    user_id: UUID
    minecraft_nickname: str
    nickname_locked: bool
    legacy_auth_enabled: bool
    legacy_hash_algo: str | None = None
    created_at: datetime


class AdminPlayerDiagnostics(BaseModel):
    legacy_hash_present: bool
    legacy_ready: bool
    must_use_launcher: bool
    refresh_sessions_active: int


class AdminPlayerRecord(BaseModel):
    user: AdminUserRead
    player_account: AdminPlayerAccountRead
    diagnostics: AdminPlayerDiagnostics


class AdminPlayersListResponse(BaseModel):
    total: int
    items: list[AdminPlayerRecord]


class AdminLegacySummaryResponse(BaseModel):
    total_players: int
    legacy_enabled_players: int
    legacy_ready_players: int
    legacy_missing_hash_players: int
    launcher_only_players: int


class AdminLegacyUpdateRequest(BaseModel):
    legacy_auth_enabled: bool | None = None
    legacy_password_hash: str | None = Field(default=None, min_length=1, max_length=512)
    legacy_hash_algo: str | None = Field(default=None, min_length=1, max_length=64)
    clear_legacy_hash: bool = False
    user_active: bool | None = None
    revoke_refresh_sessions: bool = False

    @model_validator(mode="after")
    def validate_payload(self) -> "AdminLegacyUpdateRequest":
        if self.clear_legacy_hash and (
            self.legacy_password_hash is not None or self.legacy_hash_algo is not None
        ):
            raise ValueError(
                "clear_legacy_hash cannot be used together with legacy_password_hash or legacy_hash_algo"
            )
        return self


class AdminLegacyUpdateResponse(BaseModel):
    message: str
    record: AdminPlayerRecord