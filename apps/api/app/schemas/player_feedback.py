from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from apps.api.app.models.player_feedback import FeedbackType

_VALID_TYPES = {t.value for t in FeedbackType}


class PlayerFeedbackCreate(BaseModel):
    type: str
    title: str
    body: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"type must be one of: {', '.join(_VALID_TYPES)}")
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        if len(v) > 200:
            raise ValueError("Title must be at most 200 characters")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip() or None
        return v


class PlayerFeedbackRead(BaseModel):
    id: UUID
    type: str
    title: str
    body: str | None
    created_at: datetime
    user_login: str
    user_nickname: str | None

    model_config = {"from_attributes": True}


class PlayerFeedbackListResponse(BaseModel):
    items: list[PlayerFeedbackRead]
    total: int
