"""A server in a few Telegram lines: the bot's ``/servers`` card and the Monday digest.

Built from the same data as the «Интеграция» page (``admin_integration.overview``), so the bot
and the panel never disagree.
"""
from __future__ import annotations

import html
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core.permissions import Access
from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_incident import ServerIncident
from apps.api.app.models.server_status_sample import ServerStatusSample
from apps.api.app.models.user import User


def servers_for(session: Session, user: User) -> list[GameServer]:
    """Servers whose integration this person may see: everything for platform admins,
    otherwise where ``integration.view`` holds (external servers — the page exists only there)."""
    access = Access(user)
    rows = session.scalars(select(GameServer).order_by(GameServer.sort_order, GameServer.name)).all()
    if access.platform_admin:
        from apps.api.app.core import server_reports

        return [s for s in rows if s.is_external or server_reports.reports(session, s)]
    return [s for s in rows if s.is_external and "integration.view" in access.on(s.id)]


def can(user: User, server: GameServer, key: str) -> bool:
    return key in Access(user).on(server.id)


def overview(session: Session, server: GameServer) -> dict[str, Any]:
    from apps.api.app.api.routes.admin_integration import overview as _overview

    return _overview(server, session)


def _site() -> str:
    return (get_settings().website_base_url or "https://void-rp.ru").rstrip("/")


def links(server: GameServer, data: dict[str, Any]) -> list[tuple[str, str]]:
    out = [("Открыть в админке", f"{_site()}/admin/integration?server={server.slug}")]
    if (data.get("status_page") or {}).get("on"):
        out.append(("Страница статуса", data["status_page"]["url"]))
    return out


def _pct(v: float | None) -> str:
    return "нет данных" if v is None else f"{v:.2f}".rstrip("0").rstrip(".") + "%"


def state_of(data: dict[str, Any]) -> tuple[str, str]:
    """(emoji, words) — the same reading as the page's hero."""
    reports = data.get("reports") or []
    if not reports:
        return "⚪", "ещё не подключён"
    if not any(r["fresh"] for r in reports):
        return "🔴", "нет связи — плагины молчат"
    if data.get("missing_required"):
        return "🟠", "не работает: " + ", ".join(data["missing_required"])
    return "🟢", "на связи"


def card(server: GameServer, data: dict[str, Any], *, muted_until: str | None = None) -> str:
    emoji, words = state_of(data)
    st = data.get("status") or {}
    last = next((p for p in reversed(st.get("series_24h") or []) if p.get("online") is not None), None)
    lines = [f"{emoji} <b>{html.escape(server.name)}</b> — {html.escape(words)}"]
    if server.maintenance:
        lines.append("🛠 техработы — игроки не видят сервер")
    live = []
    if last:
        live.append(f"игроков {int(last['online'])}")
        if last.get("tps") is not None:
            live.append(f"TPS {last['tps']:.1f}")
    reach = data.get("reach")
    if reach:
        live.append(f"снаружи {reach['latency_ms']} мс" if reach.get("ok") else "снаружи недоступен")
    if live:
        lines.append("📊 " + " · ".join(live))
    lines.append(f"⏱ доступность: сутки {_pct(st.get('uptime_24h'))}, неделя {_pct(st.get('uptime_7d'))}")
    health = data.get("health") or {}
    if health.get("grade"):
        lines.append(f"🏅 оценка подключения: <b>{health['grade']}</b> ({health.get('score')}/100)")
    outdated = [i for i in data.get("items") or [] if i.get("outdated") and not i.get("client_side")]
    if outdated:
        names = ", ".join(f"{i['name']} {(i.get('installed') or {}).get('version') or ''} → {(i.get('latest') or {}).get('version') or '?'}"
                          for i in outdated[:4])
        lines.append(f"⬆️ обновления: {html.escape(names)}")
    open_inc = [i for i in data.get("incidents") or [] if not i.get("ended_at")]
    if open_inc:
        lines.append(f"🔥 сейчас идёт сбой: {html.escape(open_inc[0].get('detail') or '')}")
    settings = data.get("settings") or {}
    lines.append("🔁 автообновление: " + ("включено" if settings.get("auto_update") else "выключено"))
    diag = data.get("diagnosis") or {}
    top = next((f for f in diag.get("findings") or [] if f.get("severity") in ("err", "warn")), None)
    if top:
        lines.append(f"\n💡 {html.escape(top['title'])}" + (f"\n{html.escape(top['steps'][0])}" if top.get("steps") else ""))
    if muted_until:
        lines.append(f"\n🔕 оповещения о сбоях выключены до {muted_until}")
    return "\n".join(lines)


def week_numbers(session: Session, server: GameServer) -> dict[str, Any]:
    since = utc_now() - timedelta(days=7)
    peak, avg_tps = session.execute(
        select(func.max(ServerStatusSample.online), func.avg(ServerStatusSample.tps))
        .where(ServerStatusSample.server_id == server.id, ServerStatusSample.at >= since)).one()
    incidents = session.scalars(select(ServerIncident).where(
        ServerIncident.server_id == server.id, ServerIncident.started_at >= since)).all()
    down_min = sum(int(((i.ended_at or utc_now()) - i.started_at).total_seconds() // 60) for i in incidents if i.kind == "down")
    return {"peak": peak, "avg_tps": round(float(avg_tps), 1) if avg_tps is not None else None,
            "incidents": len(incidents), "down_minutes": down_min}


def digest(session: Session, server: GameServer, data: dict[str, Any]) -> str:
    w = week_numbers(session, server)
    st = data.get("status") or {}
    emoji, words = state_of(data)
    lines = [f"📅 <b>{html.escape(server.name)}</b> — неделя", f"{emoji} сейчас: {html.escape(words)}",
             f"⏱ доступность за неделю: <b>{_pct(st.get('uptime_7d'))}</b>"]
    if w["incidents"]:
        lines.append(f"🔥 сбоев: {w['incidents']}" + (f", простой {w['down_minutes']} мин" if w["down_minutes"] else ""))
    else:
        lines.append("✅ сбоев не было")
    if w["peak"] is not None:
        lines.append(f"👥 пик онлайна: {w['peak']}")
    if w["avg_tps"] is not None:
        lines.append(f"⚙️ средний TPS: {w['avg_tps']}")
    health = data.get("health") or {}
    if health.get("grade"):
        lines.append(f"🏅 оценка подключения: <b>{health['grade']}</b>")
    outdated = [i for i in data.get("items") or [] if i.get("outdated") and not i.get("client_side")]
    if outdated:
        lines.append("⬆️ ждут обновления: " + html.escape(", ".join(i["name"] for i in outdated)))
    todo = [f["title"] for f in (data.get("diagnosis") or {}).get("findings") or [] if f.get("severity") in ("err", "warn")]
    if todo:
        lines.append("📝 сделать: " + html.escape("; ".join(todo[:3])))
    return "\n".join(lines)
