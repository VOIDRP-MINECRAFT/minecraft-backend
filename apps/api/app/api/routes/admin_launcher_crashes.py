from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.models.launcher_crash_report import LauncherCrashReport

router = APIRouter(
    prefix="/admin/launcher-crashes",
    tags=["admin", "launcher-crashes"],
    dependencies=[Depends(require_admin_access)],
)


class CrashReportItem(BaseModel):
    id: str
    player_nickname: str
    exit_code: int
    crash_report: str | None
    created_at: str

    model_config = {"from_attributes": True}


class CrashReportListResponse(BaseModel):
    items: list[CrashReportItem]
    total: int


@router.get("", response_model=CrashReportListResponse)
def list_crashes(
    session: Annotated[Session, Depends(get_db_session)],
    player: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> CrashReportListResponse:
    q = select(LauncherCrashReport).order_by(desc(LauncherCrashReport.created_at))
    if player:
        q = q.where(LauncherCrashReport.player_nickname.ilike(f"%{player}%"))

    count_q = select(func.count()).select_from(LauncherCrashReport)
    if player:
        count_q = count_q.where(LauncherCrashReport.player_nickname.ilike(f"%{player}%"))
    total = session.scalar(count_q) or 0

    rows = session.scalars(q.limit(limit).offset(offset)).all()

    return CrashReportListResponse(
        items=[
            CrashReportItem(
                id=str(r.id),
                player_nickname=r.player_nickname,
                exit_code=r.exit_code,
                crash_report=r.crash_report,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ],
        total=total,
    )


@router.delete("/{crash_id}", status_code=204)
def delete_crash(
    crash_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    row = session.get(LauncherCrashReport, crash_id)
    if row:
        session.delete(row)
        session.commit()
