"""Telling the people who run an external server what concerns it, in Telegram.

Who hears: the staff holding ``integration.view`` on that server through their own grants —
its server admins, roles, personal grants — with a linked Telegram. Platform admins see every
server and get the admin banner instead of a message per partner. Each one picks what they
want in ``users.integration_notify``.

What: a new build of one of our plugins that suits the server while it runs an older one
(``announce_releases``, from the GitHub sync), a required module that went quiet and came back
(``check_health``, from cron), a changed server secret (``notify_secret_rotated``). Every notice
is written to ``integration_notices`` first, so it goes out once however often a job runs.
"""
from __future__ import annotations

import html
import logging
from datetime import timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import server_reports
from apps.api.app.core.permissions import Access
from apps.api.app.core.releases import version_key
from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.integration_notice import IntegrationNotice
from apps.api.app.models.plugin_release import PluginRelease
from apps.api.app.models.server_report import ServerPluginReport
from apps.api.app.models.user import User

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {"releases": "all", "beta": False, "health": True}
# A required module quiet this long is "down" (a restart takes a couple of minutes).
QUIET_AFTER = timedelta(minutes=5)
CHANGELOG_LIMIT = 900


def prefs(user: User) -> dict[str, Any]:
    return {**DEFAULTS, **(user.integration_notify or {})}


def recipients(session: Session, server: GameServer) -> list[User]:
    """Staff who run this server (not via platform admin) and linked Telegram."""
    out = []
    for user in session.scalars(select(User).where(User.telegram_user_id.is_not(None), User.is_active.is_(True))).all():
        access = Access(user)
        if access.platform_admin:
            continue
        if "integration.view" in access.on(server.id):
            out.append(user)
    return out


def _site() -> str:
    return (get_settings().website_base_url or "https://void-rp.ru").rstrip("/")


def _integration_url(server: GameServer) -> str:
    return f"{_site()}/admin/integration?server={server.slug}"


def _send(chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> bool:
    from apps.api.app.services.news_service import _http_post_json

    token = get_settings().telegram_bot_token
    if not token:
        return False
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                               "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u}] for t, u in buttons]}
    return _http_post_json(f"https://api.telegram.org/bot{token}/sendMessage", payload)


def _once(session: Session, server: GameServer, user: User, kind: str, ref: str) -> IntegrationNotice | None:
    """Writes the notice, or returns None when this one was already given to this user."""
    notice = IntegrationNotice(server_id=server.id, user_id=user.id, kind=kind, ref=ref[:128])
    session.add(notice)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return None
    return notice


def _deliver(session: Session, server: GameServer, users: Iterable[User], kind: str, ref: str,
             text: str, buttons: list[tuple[str, str]] | None = None) -> int:
    sent = 0
    for user in users:
        notice = _once(session, server, user, kind, ref)
        if notice is None:
            continue
        notice.telegram_sent = _send(user.telegram_user_id, text, buttons)
        session.commit()
        sent += int(notice.telegram_sent)
    return sent


# ── New builds ────────────────────────────────────────────────────────────────
def _trim(text: str | None) -> str:
    text = (text or "").strip()
    return text if len(text) <= CHANGELOG_LIMIT else text[:CHANGELOG_LIMIT].rsplit("\n", 1)[0] + "\n…"


def announce_releases(rows: Iterable[PluginRelease]) -> int:
    """Tells every external server a fresh build suits — and that runs an older one — about it."""
    from apps.api.app.core.integration_state import suits
    from apps.api.app.db import SessionLocal

    sent = 0
    with SessionLocal() as session:
        servers = session.scalars(select(GameServer).where(GameServer.is_external.is_(True))).all()
        for row in rows:
            row = session.get(PluginRelease, row.id)
            entry = cat.entry(row.plugin) if row else None
            if row is None or entry is None or row.yanked:
                continue
            for server in servers:
                if not suits(row, server) or server.server_core not in entry["cores"]:
                    continue
                rep = session.scalar(select(ServerPluginReport).where(
                    ServerPluginReport.server_id == server.id, ServerPluginReport.plugin.ilike(entry["name"])))
                installed = rep.version if rep else None
                if installed and version_key(installed) >= version_key(row.version):
                    continue
                if not installed and not entry.get("required"):
                    continue  # not something they run
                users = [u for u in recipients(session, server) if _wants_release(u, row)]
                if not users:
                    continue
                sent += _deliver(session, server, users, "release", str(row.id),
                                 _release_text(server, entry, row, installed),
                                 [("Открыть «Интеграцию»", _integration_url(server))])
    return sent


def _wants_release(user: User, row: PluginRelease) -> bool:
    p = prefs(user)
    if row.channel == "beta" and not p["beta"]:
        return False
    return p["releases"] == "all" or (p["releases"] == "important" and row.important)


def _release_text(server: GameServer, entry: dict, row: PluginRelease, installed: str | None) -> str:
    head = "❗️ Важное обновление" if row.important else ("🧪 Бета-сборка" if row.channel == "beta" else "🆕 Обновление")
    was = f"у вас <b>{html.escape(installed)}</b> → " if installed else "не установлен → "
    lines = [
        f"{head} <b>{html.escape(entry['name'])}</b> для сервера «{html.escape(server.name)}»",
        f"{was}<b>{html.escape(row.version)}</b>",
    ]
    if row.changelog:
        lines += ["", "<b>Что изменилось:</b>", html.escape(_trim(row.changelog))]
    lines += ["", "Скачать сборку и конфиг — в «Интеграции». Paper подменит jar при перезапуске, "
                  "если положить его в <code>plugins/update/</code>."]
    return "\n".join(lines)


# ── Required modules going quiet ──────────────────────────────────────────────
def check_health() -> int:
    """External servers whose required module stopped reporting (and came back since)."""
    from apps.api.app.db import SessionLocal

    sent = 0
    now = utc_now()
    with SessionLocal() as session:
        for server in session.scalars(select(GameServer).where(GameServer.is_external.is_(True))).all():
            if server.maintenance:
                continue
            last: dict[str, Any] = {}
            for r in server_reports.reports(session, server):
                for name, state in (r.modules or {}).items():
                    if name in server_reports.REQUIRED_MODULES and isinstance(state, dict) and state.get("ok"):
                        if r.reported_at and (name not in last or r.reported_at > last[name]):
                            last[name] = r.reported_at
            users = [u for u in recipients(session, server) if prefs(u)["health"]]
            if not users:
                continue
            for name, label in server_reports.REQUIRED_MODULES.items():
                seen = last.get(name)
                if seen is None:
                    continue  # never reported: the checklist on the page covers a new server
                since = seen.strftime("%Y%m%d%H%M")
                if now - seen > QUIET_AFTER:
                    sent += _deliver(session, server, users, "module_down", f"{name}:{since}",
                                     f"⚠️ Сервер «{html.escape(server.name)}»: <b>{html.escape(label)}</b> не отвечает "
                                     f"с {seen.strftime('%H:%M')} UTC.\nПока модуль молчит, эта функция в VoidRP не работает. "
                                     "Проверьте, запущен ли сервер и нет ли ошибок плагина в консоли.",
                                     [("Открыть «Интеграцию»", _integration_url(server))])
                else:
                    sent += _recovered(session, server, users, name, label)
    return sent


def _recovered(session: Session, server: GameServer, users: list[User], name: str, label: str) -> int:
    """After a "down" notice: one "back" notice per outage."""
    sent = 0
    for user in users:
        down = session.scalars(select(IntegrationNotice).where(
            IntegrationNotice.server_id == server.id, IntegrationNotice.user_id == user.id,
            IntegrationNotice.kind == "module_down", IntegrationNotice.ref.like(f"{name}:%"),
        ).order_by(IntegrationNotice.created_at.desc())).first()
        if down is None:
            continue
        sent += _deliver(session, server, [user], "module_up", down.ref,
                         f"✅ Сервер «{html.escape(server.name)}»: <b>{html.escape(label)}</b> снова на связи.")
    return sent


# ── Secret ────────────────────────────────────────────────────────────────────
def notify_secret_rotated(session: Session, server: GameServer, by: str | None) -> int:
    ref = utc_now().strftime("%Y%m%d%H%M%S")
    who = f" ({html.escape(by)})" if by else ""
    return _deliver(session, server, recipients(session, server), "secret", ref,
                    f"🔑 Секрет сервера «{html.escape(server.name)}» сменён{who}.\n"
                    "Плагины со старым секретом перестали подключаться: скачайте новые конфиги в «Интеграции» "
                    "и перезапустите сервер.",
                    [("Открыть «Интеграцию»", _integration_url(server))])
