from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ── Game-facing (мод тянет / рапортует) ─────────────────────────────────────

class VoxelGameSync(BaseModel):
    """Что мод забирает по GET /voxel/games — минимум для загрузки и сравнения."""

    game_id: str
    name: str
    version: int
    is_active: bool
    definition: dict[str, Any]

    model_config = {"from_attributes": True}


class VoxelGameStatusReport(BaseModel):
    """Что мод постит по POST /voxel/games/{game_id}/status после загрузки."""

    status: Literal["ok", "error"]
    version: int = Field(ge=1)
    message: str | None = Field(default=None, max_length=2000)


# ── Admin CRUD (под webgui) ─────────────────────────────────────────────────

class VoxelGameCreate(BaseModel):
    game_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    definition: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_active: bool = False


class VoxelGameUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    definition: dict[str, Any] | None = None
    enabled: bool | None = None
    is_active: bool | None = None


class VoxelGameAdmin(BaseModel):
    """Полное admin-представление записи игры."""

    id: UUID
    server_id: UUID
    game_id: str
    name: str
    definition: dict[str, Any]
    version: int
    enabled: bool
    is_active: bool
    last_report_status: str | None = None
    last_report_message: str | None = None
    last_reported_version: int | None = None
    last_reported_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
