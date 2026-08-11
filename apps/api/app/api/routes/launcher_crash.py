from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.launcher_crash_report import LauncherCrashReport
from apps.api.app.models.user import User

router = APIRouter(prefix="/launcher", tags=["launcher-crash"])

MAX_CRASH_REPORT_LEN = 65_536
MAX_LOG_TAIL_LEN = 65_536


def _clip(text: str | None, limit: int) -> str | None:
    if text and len(text) > limit:
        return text[:limit] + "\n... [truncated]"
    return text or None


class CrashReportRequest(BaseModel):
    exit_code: int
    crash_report: str | None = None
    # Enriched diagnostics (all optional so older launchers keep working).
    log_tail: str | None = None
    launcher_version: str | None = None
    os_name: str | None = None
    java_version: str | None = None
    ram_mb: int | None = None
    server_slug: str | None = None


@router.post("/me/crash-report", status_code=204)
def submit_crash_report(
    body: CrashReportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    nickname = current_user.player_account.minecraft_nickname if current_user.player_account else None
    if not nickname:
        return

    record = LauncherCrashReport(
        player_nickname=nickname,
        exit_code=body.exit_code,
        crash_report=_clip(body.crash_report, MAX_CRASH_REPORT_LEN),
        log_tail=_clip(body.log_tail, MAX_LOG_TAIL_LEN),
        launcher_version=body.launcher_version,
        os_name=body.os_name,
        java_version=body.java_version,
        ram_mb=body.ram_mb,
        server_slug=body.server_slug,
    )
    session.add(record)
    session.commit()
