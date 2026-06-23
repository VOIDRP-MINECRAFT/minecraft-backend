from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VoidRP Account API"
    api_v1_prefix: str = "/api/v1"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False

    database_url: str = Field(
        default="postgresql+psycopg://voidrp:voidrp_password@localhost:5432/voidrp_accounts"
    )

    jwt_secret_key: str = Field(default="CHANGE_ME_TO_LONG_RANDOM_SECRET", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    email_token_expire_hours: int = 24

    play_ticket_expire_minutes: int = Field(default=720, ge=30, le=1440)
    game_auth_shared_secret: str = Field(
        default="CHANGE_ME_TO_STRONG_GAME_AUTH_SECRET",
        min_length=16,
    )
    admin_api_secret: str = Field(
        default="CHANGE_ME_TO_STRONG_ADMIN_SECRET",
        min_length=16,
    )

    # HMAC-SHA256 key used to sign launcher proofs embedded in play tickets.
    # Must match the value configured in the VoidRP launcher.
    # If empty, launcher proof validation is skipped (dev/migration mode).
    launcher_hmac_secret: str = Field(default="")

    # Base64-encoded 32-byte secret shared with the WebGUI Fabric mod (config/webgui/server.json).
    # Used to verify ?webgui_token= query params on game-ui routes.
    webgui_token_secret_base64: str = Field(default="")

    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "https://void-rp.ru",
            "https://www.void-rp.ru",
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:5175",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )
    cors_allow_origin_regex: str | None = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    easydonate_shop_key: str = ""
    easydonate_server_id: int = 0

    email_from: str = "VoidRP <noreply@mail.void-rp.ru>"
    email_backend: Literal["logging", "resend"] = "logging"
    resend_api_key: str | None = None
    public_api_base_url: str = "https://api.void-rp.ru"
    website_base_url: str = "https://void-rp.ru"

    media_storage_root: str = "./media"
    media_public_mount_path: str = "/media"
    media_public_base_url: str = "https://api.void-rp.ru/media"

    profile_avatar_max_bytes: int = 512 * 1024
    profile_banner_max_bytes: int = 2 * 1024 * 1024
    profile_background_max_bytes: int = 3 * 1024 * 1024

    profile_avatar_min_width: int = 256
    profile_avatar_min_height: int = 256
    profile_avatar_max_width: int = 2048
    profile_avatar_max_height: int = 2048

    profile_banner_min_width: int = 1280
    profile_banner_min_height: int = 720
    profile_banner_max_width: int = 3840
    profile_banner_max_height: int = 2160

    profile_background_min_width: int = 1600
    profile_background_min_height: int = 900
    profile_background_max_width: int = 4096
    profile_background_max_height: int = 4096

    player_skin_max_bytes: int = 3 * 1024 * 1024
    player_skin_allowed_dimensions: str = "64x64,64x32"
    player_skin_head_preview_size: int = 256
    player_skin_body_preview_width: int = 176
    player_skin_body_preview_height: int = 320

    minecraft_server_host: str = ""
    minecraft_server_port: int = 25565
    rcon_host: str = "127.0.0.1"
    rcon_port: int = 25575
    rcon_password: str = ""

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_prefix: str = "voidrp"
    redis_default_ttl_seconds: int = 30

    yandex_metrika_token: str = ""
    yandex_metrika_counter_id: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "public_api_base_url",
        "website_base_url",
        "media_public_base_url",
        "media_public_mount_path",
        mode="before",
    )
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/") if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_placeholder_secrets(self) -> "Settings":
        if self.app_env == "production":
            critical = {
                "jwt_secret_key": self.jwt_secret_key,
                "game_auth_shared_secret": self.game_auth_shared_secret,
                "admin_api_secret": self.admin_api_secret,
            }
            for field, value in critical.items():
                if value.upper().startswith("CHANGE_ME"):
                    raise ValueError(
                        f"{field} must not use the default placeholder value in production"
                    )
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env in {"development", "test"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
