"""«Скачать лаунчер» clicks on the site, for the newcomer funnel (core/funnel.py)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_optional_current_user
from apps.api.app.models.retention import LauncherDownload
from apps.api.app.models.user import User

router = APIRouter(prefix="/launcher", tags=["launcher"])


class DownloadEvent(BaseModel):
    platform: str = Field(default="other", pattern=r"^(windows|linux|mac|other)$")


@router.post("/download-event", status_code=status.HTTP_204_NO_CONTENT)
def download_event(payload: DownloadEvent, session: Annotated[Session, Depends(get_db_session)],
                   user: Annotated[User | None, Depends(get_optional_current_user)]) -> None:
    session.add(LauncherDownload(user_id=user.id if user else None, platform=payload.platform))
    session.commit()
