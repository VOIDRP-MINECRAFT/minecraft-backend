"""«Скачать лаунчер» clicks on the site, for the newcomer funnel (core/funnel.py), and reports
from launchers that could not start (no account needed: a launcher that fails has no session)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core.audit import client_ip
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_optional_current_user
from apps.api.app.models.launcher_crash_report import LauncherBootReport
from apps.api.app.models.retention import LauncherDownload
from apps.api.app.models.user import User
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(prefix="/launcher", tags=["launcher"])


class DownloadEvent(BaseModel):
    platform: str = Field(default="other", pattern=r"^(windows|linux|mac|other)$")


@router.post("/download-event", status_code=status.HTTP_204_NO_CONTENT)
def download_event(payload: DownloadEvent, session: Annotated[Session, Depends(get_db_session)],
                   user: Annotated[User | None, Depends(get_optional_current_user)]) -> None:
    session.add(LauncherDownload(user_id=user.id if user else None, platform=payload.platform))
    session.commit()


class BootReport(BaseModel):
    launcher_version: str | None = Field(default=None, max_length=32)
    os_name: str | None = Field(default=None, max_length=160)
    error: str = Field(min_length=1, max_length=4000)
    hint: str | None = Field(default=None, max_length=2000)
    report: str | None = Field(default=None, max_length=20000)
    main_log_tail: str | None = Field(default=None, max_length=20000)


# Open to anyone, so a few per address per hour: a player pressing «Повторить» several times
# still gets through, a script does not fill the table.
_BOOT_REPORTS_PER_HOUR = 10


@router.post("/boot-report", status_code=status.HTTP_204_NO_CONTENT)
def boot_report(payload: BootReport, request: Request, session: Annotated[Session, Depends(get_db_session)]) -> None:
    cache = RedisCacheService()
    key = f"launcher_boot_report:{client_ip(request) or 'unknown'}"
    count = int(cache.get_json(key) or 0)
    if count >= _BOOT_REPORTS_PER_HOUR:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many reports")
    cache.set_json(key, count + 1, ttl_seconds=3600)

    session.add(LauncherBootReport(**payload.model_dump()))
    session.commit()
