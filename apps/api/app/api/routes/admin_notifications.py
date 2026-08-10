from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import caller_permissions, get_current_staff_user
from apps.api.app.models.anticheat import AnticheatInjectionReport
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.launcher_crash_report import LauncherCrashReport
from apps.api.app.models.mod_suggestion import ModSuggestion
from apps.api.app.models.player_feedback import PlayerFeedback
from apps.api.app.models.user import User
from apps.api.app.schemas.admin_notification import AdminNotification, AdminNotificationsResponse

router = APIRouter(prefix="/admin/notifications", tags=["admin", "notifications"])

_WINDOW = timedelta(hours=24)


def _count_since(session: Session, model, since: datetime) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(model.created_at >= since)) or 0)


@router.get("", response_model=AdminNotificationsResponse)
def list_notifications(
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    _: Annotated[User, Depends(get_current_staff_user)],
) -> AdminNotificationsResponse:
    """Actionable, permission-scoped notifications for the admin banner.

    Each item is only produced when the caller holds the relevant permission,
    so moderators never see alerts for areas they cannot access. Levels:
    error > warning > info. The frontend also merges its own transient client
    alerts (e.g. a failed news broadcast) into the same banner.
    """
    since = datetime.now(timezone.utc) - _WINDOW
    items: list[AdminNotification] = []

    if "feedback.view" in perms:
        n = _count_since(session, PlayerFeedback, since)
        if n:
            items.append(AdminNotification(
                id="feedback-new", level="info", count=n,
                title="Новые обращения",
                message=f"{n} новых обращений за сутки — загляни в раздел «Обращения».",
                link="/admin/feedback",
            ))

    if "mod_suggestions.view" in perms:
        n = _count_since(session, ModSuggestion, since)
        if n:
            items.append(AdminNotification(
                id="mod-suggestions-new", level="info", count=n,
                title="Новые предложения модов",
                message=f"{n} новых предложений модов за сутки.",
                link="/admin/mod-suggestions",
            ))

    if "crashes.view" in perms:
        n = _count_since(session, LauncherCrashReport, since)
        if n:
            items.append(AdminNotification(
                id="crashes-24h", level="warning", count=n,
                title="Краши лаунчера",
                message=f"{n} крашей лаунчера за последние сутки.",
                link="/admin/launcher-crashes",
            ))

    if "anticheat.view" in perms:
        # Injection reports are the sharp "possible cheater" signal — surfaced.
        # The raw unreviewed-violations backlog is intentionally NOT a banner
        # (it's a large standing number, not an actionable alert).
        injections = _count_since(session, AnticheatInjectionReport, since)
        if injections:
            items.append(AdminNotification(
                id="anticheat-injections", level="error", count=injections,
                title="Отчёты об инъекциях",
                message=f"{injections} отчётов об инъекциях в клиент за сутки — возможные читеры.",
                link="/admin/anticheat",
            ))

    if "monitoring.view" in perms or "servers.manage" in perms:
        maint = session.scalars(
            select(GameServer).where(GameServer.maintenance.is_(True)).order_by(GameServer.sort_order)
        ).all()
        for s in maint:
            items.append(AdminNotification(
                id=f"maintenance-{s.slug}", level="warning", count=1,
                title="Технические работы",
                message=f"Сервер «{s.name}» в режиме тех. работ.",
                link="/admin/server",
            ))

    return AdminNotificationsResponse(items=items)
