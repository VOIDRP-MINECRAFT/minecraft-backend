from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NotificationLevel = Literal["info", "warning", "error", "success"]


class AdminNotification(BaseModel):
    id: str
    level: NotificationLevel = "info"
    title: str
    message: str
    link: str | None = None
    count: int | None = None


class AdminNotificationsResponse(BaseModel):
    items: list[AdminNotification]
