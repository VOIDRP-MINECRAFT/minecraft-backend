from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

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
from apps.api.app.models.server_watchdog import ServerWatchdogEvent
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
    me: Annotated[User, Depends(get_current_staff_user)],
) -> AdminNotificationsResponse:
    """Actionable, permission-scoped notifications for the admin banner.

    Each item is only produced when the caller holds the relevant permission,
    so moderators never see alerts for areas they cannot access. Levels:
    error > warning > info. The frontend also merges its own transient client
    alerts (e.g. a failed news broadcast) into the same banner.
    """
    since = datetime.now(timezone.utc) - _WINDOW
    items: list[AdminNotification] = []

    # Feedback and suggestions come from every server: count those of the servers this
    # person may see (untagged ones only with the permission on every server).
    from apps.api.app.core.permissions import access_of, servers_with_permission
    access = access_of(me)
    slug_of = {i: slug for i, slug in session.execute(select(GameServer.id, GameServer.slug)).all()}

    def _count_on(model, key: str, by_slug: bool = False) -> int:
        if access.holds_everywhere(key):
            return _count_since(session, model, since)
        ids = [UUID(i) for i in access.servers_with(key, slug_of)]
        if not ids:
            return 0
        where = model.server_slug.in_([slug_of[i] for i in ids]) if by_slug else model.server_id.in_(ids)
        return session.scalar(select(func.count()).select_from(model).where(
            model.created_at >= since, where)) or 0

    if n := _count_on(PlayerFeedback, "feedback.view"):
        items.append(AdminNotification(
            id="feedback-new", level="info", count=n,
            title="Новые обращения",
            message=f"{n} новых обращений за сутки — загляни в раздел «Обращения».",
            link="/admin/feedback",
        ))

    if n := _count_on(ModSuggestion, "mod_suggestions.view"):
        items.append(AdminNotification(
            id="mod-suggestions-new", level="info", count=n,
            title="Новые предложения модов",
            message=f"{n} новых предложений модов за сутки.",
            link="/admin/mod-suggestions",
        ))

    if n := _count_on(LauncherCrashReport, "crashes.view", by_slug=True):
        items.append(AdminNotification(
            id="crashes-24h", level="warning", count=n,
            title="Краши лаунчера",
            message=f"{n} крашей лаунчера за последние сутки.",
            link="/admin/launcher-crashes",
        ))

    if "anticheat.view" in perms:
        # Only *meaningful* injection reports are the "possible cheater" signal.
        # The mod also POSTs an empty "all clear" report on every login
        # (agents_detected=false, empty agent/library lists) — counting those
        # produced a false "50 possible cheaters" banner with nothing to see in
        # the tab. So require an actual detection: a JVM agent, or a non-empty
        # suspicious-library list. The raw unreviewed-violations backlog is
        # intentionally NOT a banner (large standing number, not actionable).
        injections = int(session.scalar(
            select(func.count()).select_from(AnticheatInjectionReport).where(
                AnticheatInjectionReport.created_at >= since,
                (AnticheatInjectionReport.agents_detected.is_(True))
                | (AnticheatInjectionReport.suspicious_libraries.notin_(["[]", ""])),
            )
        ) or 0)
        if injections:
            items.append(AdminNotification(
                id="anticheat-injections", level="error", count=injections,
                title="Отчёты об инъекциях",
                message=f"{injections} отчётов об инъекциях в клиент за сутки — возможные читеры.",
                link="/admin/anticheat",
            ))

    # Our plugins an external server runs in an older version than the one offered.
    from apps.api.app.core import integration_state
    for srv in session.scalars(select(GameServer).where(GameServer.is_external.is_(True))).all():
        if "integration.view" not in access.on(srv.id):
            continue
        old = integration_state.outdated(session, srv)
        if old:
            names = ", ".join(f"{o['name']} {o['installed']} → {o['latest']}" for o in old)
            items.append(AdminNotification(
                id=f"integration-outdated-{srv.slug}",
                level="error" if any(o["important"] for o in old) else "warning",
                count=len(old),
                title="Есть обновления плагинов VoidRP",
                message=f"Сервер «{srv.name}»: {names}.",
                link=f"/admin/integration?server={srv.slug}",
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

    # Servers whose monitoring this person may see — the watchdog's news is per server.
    from apps.api.app.core.permissions import servers_with_permission
    watch_ids = servers_with_permission(me, "monitoring.view", [i for (i,) in session.execute(select(GameServer.id)).all()])
    if watch_ids:
        # What the watchdog did or could not do in the last day, per server: a restart is
        # worth knowing about, a server it could not bring back needs someone.
        rows = session.execute(
            select(GameServer.name, ServerWatchdogEvent.kind, func.count(), func.max(ServerWatchdogEvent.created_at))
            .join(GameServer, GameServer.id == ServerWatchdogEvent.server_id)
            .where(ServerWatchdogEvent.created_at >= since,
                   ServerWatchdogEvent.server_id.in_([UUID(i) for i in watch_ids]),
                   ServerWatchdogEvent.kind.in_(("restart", "hang", "limit", "down")))
            .group_by(GameServer.name, ServerWatchdogEvent.kind)
        ).all()
        words = {
            "restart": ("warning", "перезапускал зависший сервер", "раз"),
            "hang": ("error", "сервер завис и не перезапущен", "раз"),
            "limit": ("error", "сервер зависает снова и снова — перезапуски остановлены", "раз"),
            "down": ("error", "сервер был выключен", "раз"),
        }
        for name, kind, n, last in rows:
            level, what, _unit = words[kind]
            items.append(AdminNotification(
                id=f"watchdog-{kind}-{name}", level=level, count=n,
                title=f"Вотчдог · {name}",
                message=f"За сутки: {what} ({n}). Последний раз — {last.astimezone().strftime('%d.%m %H:%M')}. "
                        "Подробности и дамп потоков — «Мониторинг» → «Присмотр за сервером».",
                link="/admin/monitoring",
            ))

    return AdminNotificationsResponse(items=items)


def _parse_since(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return default


@router.get("/nav-counts")
def nav_counts(
    session: Annotated[Session, Depends(get_db_session)],
    me: Annotated[User, Depends(get_current_staff_user)],
    feedback: str | None = None,
    suggestions: str | None = None,
    crashes: str | None = None,
    server: str | None = None,
) -> dict:
    """Numbers next to menu items: what arrived since this person last opened the section
    (the browser keeps those times, passed as ISO in the query; default — the last 7 days),
    and unreviewed anticheat violations of the selected server for the last day. Same
    permission rules as the banner; a key is absent when the caller may not see it."""
    from apps.api.app.core.permissions import access_of
    from apps.api.app.models.anticheat import AnticheatViolation

    access = access_of(me)
    week = datetime.now(timezone.utc) - timedelta(days=7)
    slug_of = {i: slug for i, slug in session.execute(select(GameServer.id, GameServer.slug)).all()}

    def count(model, key: str, since: datetime, by_slug: bool = False) -> int | None:
        if access.holds_everywhere(key):
            return int(session.scalar(select(func.count()).select_from(model).where(model.created_at >= since)) or 0)
        ids = [UUID(i) for i in access.servers_with(key, slug_of)]
        if not ids:
            return None
        where = model.server_slug.in_([slug_of[i] for i in ids]) if by_slug else model.server_id.in_(ids)
        return int(session.scalar(select(func.count()).select_from(model).where(model.created_at >= since, where)) or 0)

    out: dict[str, int] = {}
    for name, model, key, raw, by_slug in (
        ("feedback", PlayerFeedback, "feedback.view", feedback, False),
        ("suggestions", ModSuggestion, "mod_suggestions.view", suggestions, False),
        ("crashes", LauncherCrashReport, "crashes.view", crashes, True),
    ):
        n = count(model, key, _parse_since(raw, week), by_slug)
        if n is not None:
            out[name] = n
    srv = session.scalar(select(GameServer).where(GameServer.slug == server)) if server else None
    if srv is not None and "anticheat.view" in access.on(srv.id):
        out["anticheat"] = int(session.scalar(select(func.count()).select_from(AnticheatViolation).where(
            AnticheatViolation.server_id == srv.id, AnticheatViolation.reviewed.is_(False),
            AnticheatViolation.created_at >= datetime.now(timezone.utc) - _WINDOW)) or 0)
    return out


@router.get("/feed")
def feed(
    session: Annotated[Session, Depends(get_db_session)],
    me: Annotated[User, Depends(get_current_staff_user)],
    limit: int = 40,
) -> dict:
    """«Лента событий» (side panel): staff actions, server outages and new plugin builds in
    one timeline, newest first. Each source only with its permission: the audit log with
    ``audit.view`` on every server, incidents of servers with ``monitoring.view`` /
    ``integration.view``, builds for anyone who sees an integration page."""
    from apps.api.app.core.permissions import access_of
    from apps.api.app.models.admin_audit_log import AdminAuditLog
    from apps.api.app.models.plugin_release import PluginRelease
    from apps.api.app.models.server_incident import ServerIncident

    access = access_of(me)
    limit = max(5, min(limit, 100))
    week = datetime.now(timezone.utc) - timedelta(days=7)
    servers = session.scalars(select(GameServer)).all()
    name_of = {s.id: s.name for s in servers}
    events: list[dict] = []

    if access.holds_everywhere("audit.view"):
        for r in session.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)).all():
            events.append({"kind": "audit", "at": r.created_at.isoformat(), "who": r.actor_name, "category": r.category,
                           "action": r.action, "target": r.target_label, "server": name_of.get(r.server_id)})

    watch = [s.id for s in servers if {"monitoring.view", "integration.view"} & access.on(s.id)]
    if watch:
        for i in session.scalars(select(ServerIncident).where(ServerIncident.server_id.in_(watch), ServerIncident.started_at >= week)
                                 .order_by(ServerIncident.started_at.desc()).limit(limit)).all():
            events.append({"kind": "incident", "at": i.started_at.isoformat(), "server": name_of.get(i.server_id),
                           "incident": i.kind, "detail": i.detail, "ended_at": i.ended_at.isoformat() if i.ended_at else None})

    if any("integration.view" in access.on(s.id) for s in servers):
        from apps.api.app.core import integration_catalog as cat

        seen_builds: set[tuple[str, str]] = set()
        for r in session.scalars(select(PluginRelease).where(PluginRelease.yanked.is_(False), PluginRelease.published_at >= week)
                                 .order_by(PluginRelease.published_at.desc()).limit(15)).all():
            if (r.plugin, r.version) in seen_builds:
                continue  # one build may ship several jars (per platform / MC version)
            seen_builds.add((r.plugin, r.version))
            events.append({"kind": "release", "at": r.published_at.isoformat(), "plugin": (cat.entry(r.plugin) or {}).get("name") or r.plugin,
                           "version": r.version, "important": r.important, "channel": r.channel})

    events.sort(key=lambda e: e["at"], reverse=True)
    return {"events": events[:limit]}
