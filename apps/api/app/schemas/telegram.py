from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramLinkRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=64)


class TelegramLinkStatus(BaseModel):
    linked: bool
    telegram_username: str | None = None
    telegram_user_id: int | None = None
