from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class GameServerStatus(BaseModel):
    online: bool = False
    players_online: int = 0
    players_max: int = 0
    version: str | None = None


class GameServerPublic(BaseModel):
    """Showcase-safe view (no secret) for launcher / site server list."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    icon_url: str | None = None
    banner_url: str | None = None
    sort_order: int = 0
    host: str
    port: int
    mc_version: str
    loader: str
    java_version: int
    manifest_url: str | None = None
    pack_version: str
    min_launcher_version: str
    max_players: int
    whitelist_mode: str
    maintenance: bool
    status: GameServerStatus | None = None

    model_config = {"from_attributes": True}


class GameServerAdmin(GameServerPublic):
    """Full admin view — adds internal / config fields."""

    is_visible: bool
    is_default: bool
    neoforge_version: str | None = None
    pack_root: str | None = None
    pack_base_url: str | None = None
    status_host: str | None = None
    status_port: int | None = None
    game_auth_secret: str

    model_config = {"from_attributes": True}


class GameServerCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    icon_url: str | None = None
    banner_url: str | None = None
    sort_order: int = 0
    is_visible: bool = True
    is_default: bool = False

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=25565, ge=1, le=65535)
    mc_version: str = "1.21.1"
    loader: str = "neoforge"
    java_version: int = 21
    neoforge_version: str | None = None

    pack_root: str | None = None
    pack_base_url: str | None = None
    manifest_url: str | None = None
    pack_version: str = "1.0.0"
    min_launcher_version: str = "0.1.0"

    status_host: str | None = None
    status_port: int | None = Field(default=None, ge=1, le=65535)
    max_players: int = Field(default=100, ge=1)
    whitelist_mode: str = Field(default="public", pattern=r"^(public|whitelist|invite)$")
    maintenance: bool = False

    # If omitted, a strong secret is generated server-side.
    game_auth_secret: str | None = None


class GameServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    icon_url: str | None = None
    banner_url: str | None = None
    sort_order: int | None = None
    is_visible: bool | None = None
    is_default: bool | None = None

    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    mc_version: str | None = None
    loader: str | None = None
    java_version: int | None = None
    neoforge_version: str | None = None

    pack_root: str | None = None
    pack_base_url: str | None = None
    manifest_url: str | None = None
    pack_version: str | None = None
    min_launcher_version: str | None = None

    status_host: str | None = None
    status_port: int | None = Field(default=None, ge=1, le=65535)
    max_players: int | None = Field(default=None, ge=1)
    whitelist_mode: str | None = Field(default=None, pattern=r"^(public|whitelist|invite)$")
    maintenance: bool | None = None
