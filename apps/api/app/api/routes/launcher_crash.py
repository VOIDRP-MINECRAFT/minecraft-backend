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


class CrashReportRequest(BaseModel):
    exit_code: int
    crash_report: str | None = None


@router.post("/me/crash-report", status_code=204)
def submit_crash_report(
    body: CrashReportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    nickname = current_user.player_account.minecraft_nickname if current_user.player_account else None
    if not nickname:
        return

    crash_report = body.crash_report
    if crash_report and len(crash_report) > MAX_CRASH_REPORT_LEN:
        crash_report = crash_report[:MAX_CRASH_REPORT_LEN] + "\n... [truncated]"

    record = LauncherCrashReport(
        player_nickname=nickname,
        exit_code=body.exit_code,
        crash_report=crash_report,
    )
    session.add(record)
    session.commit()
