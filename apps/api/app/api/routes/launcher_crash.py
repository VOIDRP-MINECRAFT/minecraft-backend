from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.launcher_crash_report import LauncherCrashReport
from apps.api.app.models.user import User
from apps.api.app.services.launcher_crash_rules_service import rules_for_server

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
    # Key of the launcher crash rule that recognized the crash (launcher 4.0.41+).
    advice_rule_key: str | None = None


@router.get("/crash-rules")
def get_crash_rules(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Crash rules the launcher merges over its built-ins (disabled ones included — they switch
    a built-in off), plus the pre-launch memory threshold. Public: the launcher may ask before login."""
    return {
        "recommended_ram_mb": server.launcher_recommended_ram_mb,
        "rules": rules_for_server(session, server),
    }


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
        advice_rule_key=(body.advice_rule_key or None) and body.advice_rule_key[:64],
    )
    session.add(record)
    session.commit()
