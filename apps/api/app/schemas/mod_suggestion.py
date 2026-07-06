from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, field_validator

_ALLOWED_HOSTS = frozenset({
    "modrinth.com",
    "www.modrinth.com",
    "curseforge.com",
    "www.curseforge.com",
    "minecraft-inside.ru",
    "www.minecraft-inside.ru",
})


class ModSuggestionCreate(BaseModel):
    url: str
    comment: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required")
        try:
            src = v if "://" in v else f"https://{v}"
            host = urlparse(src).netloc.lower()
        except Exception:
            raise ValueError("Invalid URL format")
        if host not in _ALLOWED_HOSTS:
            raise ValueError(
                "Allowed sources: modrinth.com, curseforge.com, minecraft-inside.ru"
            )
        return v


class ModSuggestionRead(BaseModel):
    id: UUID
    url: str
    comment: str | None
    created_at: datetime
    user_login: str
    user_nickname: str | None
    server_name: str | None = None

    model_config = {"from_attributes": True}


class ModSuggestionListResponse(BaseModel):
    items: list[ModSuggestionRead]
    total: int
