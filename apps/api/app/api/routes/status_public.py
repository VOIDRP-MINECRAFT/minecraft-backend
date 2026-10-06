"""Public status of a game server: a page on the site, a badge, JSON for the partner's site.

* ``GET /status/{slug}`` — JSON: online now, players, TPS, uptime 24h/7d/30d, 30 daily bars,
  incidents of the month, the connection grade. Open to any site (CORS ``*``).
* ``GET /status/{slug}/badge.svg`` — a shields-style badge for Discord, GitHub, a forum.

Only for servers whose status is public: a listed server by default, or by the owner's switch
in «Интеграция» (``integration_settings.public_status``). Cached 30–60 s.
"""
from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import integration_reach, server_status
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_status_sample import ServerStatusSample
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(prefix="/status", tags=["status"])
_Db = Annotated[Session, Depends(get_db_session)]
_CORS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=30"}


def _public_server(session: Session, slug: str) -> GameServer:
    from apps.api.app.api.routes.admin_integration import public_status_on

    server = session.scalar(select(GameServer).where(GameServer.slug == slug.lower()))
    if server is None or not public_status_on(server):
        raise HTTPException(status_code=404, detail="Статус этого сервера не публичный")
    return server


def build(session: Session, server: GameServer) -> dict:
    cache = RedisCacheService()
    key = f"public_status:{server.id}"
    cached = cache.get_json(key)
    if cached:
        return cached
    last = session.scalar(select(ServerStatusSample).where(ServerStatusSample.server_id == server.id)
                          .order_by(ServerStatusSample.at.desc()).limit(1))
    summary = server_status.summary(session, server)
    online, players, max_players = bool(last and last.up), last and last.online, last and last.max_players
    if last is None or (utc_now() - last.at).total_seconds() > 900:
        # No monitoring reports (our own servers live on RCON) — ask the server itself, from outside.
        ping = integration_reach.check(server)
        online, players, max_players = bool(ping.get("ok")), ping.get("players"), ping.get("max")
    grade = None
    try:
        from apps.api.app.api.routes.admin_integration import overview

        grade = (overview(server, session).get("health") or {}).get("grade")
    except Exception:  # noqa: BLE001 — the grade is a bonus, never a reason to fail the page
        grade = None
    data = {
        "slug": server.slug, "name": server.name, "description": server.description,
        "icon_url": server.icon_url, "banner_url": server.banner_url, "accent_color": getattr(server, "accent_color", None),
        "address": f"{server.host}{'' if int(server.port or 25565) == 25565 else f':{server.port}'}" if server.host else None,
        "mc_version": server.mc_version, "maintenance": server.maintenance,
        "online": online and not server.maintenance,
        "players": players, "max_players": max_players or server.max_players,
        "tps": round(last.tps, 1) if last and last.tps is not None else None,
        "updated_at": last.at.isoformat() if last else None,
        "uptime_24h": summary["uptime_24h"], "uptime_7d": summary["uptime_7d"], "uptime_30d": summary["uptime_30d"],
        "peak_24h": summary["peak_24h"], "bars_30d": summary["bars_30d"],
        "series_24h": [{"t": p["t"], "online": p["online"]} for p in summary["series_24h"]],
        "incidents": [{k: i[k] for k in ("kind", "started_at", "ended_at", "minutes")}
                      for i in server_status.incidents(session, server)],
        "grade": grade,
        "page_url": f"{(get_settings().website_base_url or 'https://void-rp.ru').rstrip('/')}/status/{server.slug}",
    }
    cache.set_json(key, data, ttl_seconds=30)
    return data


@router.api_route("/{slug}", methods=["GET", "HEAD"])
def public_status(slug: str, session: _Db) -> JSONResponse:
    return JSONResponse(build(session, _public_server(session, slug)), headers=_CORS)


def _text_width(text: str, bold: bool = False) -> int:
    # Verdana/DejaVu 11px, the badge font, with room to spare: Cyrillic and capitals run wide.
    w = sum(8.4 if c.isupper() or c in "mwшщжюыМШЩЖЮЫ" else 4.0 if c in " .:il|" else 7.2 for c in text)
    return int(w * (1.1 if bold else 1.0) + 12)


@router.api_route("/{slug}/badge.svg", methods=["GET", "HEAD"])
def badge(slug: str, session: _Db) -> Response:
    server = _public_server(session, slug)
    d = build(session, server)
    left = server.name[:28]
    if d["maintenance"]:
        right, color = "техработы", "#d97706"
    elif d["online"]:
        right = f"● {d['players'] or 0}/{d['max_players'] or '?'} онлайн"
        color = "#16a34a"
    else:
        right, color = "● офлайн", "#dc2626"
    lw, rw = _text_width(left) + 22, _text_width(right, bold=True)
    w = lw + rw
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="22" role="img" aria-label="{escape(left)}: {escape(right)}">
<title>{escape(left)}: {escape(right)}</title>
<linearGradient id="g" x2="0" y2="100%"><stop offset="0" stop-color="#fff" stop-opacity=".12"/><stop offset="1" stop-opacity=".12"/></linearGradient>
<clipPath id="r"><rect width="{w}" height="22" rx="5" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{lw}" height="22" fill="#2a1a4a"/><rect x="{lw}" width="{rw}" height="22" fill="{color}"/><rect width="{w}" height="22" fill="url(#g)"/></g>
<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
<circle cx="11" cy="11" r="5" fill="#a78bfa"/><path d="M8.6 9.2l2.4 4.4 2.4-4.4" stroke="#2a1a4a" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
<text x="{22 + (lw - 22) / 2}" y="15" text-anchor="middle">{escape(left)}</text>
<text x="{lw + rw / 2}" y="15" text-anchor="middle" font-weight="bold">{escape(right)}</text></g></svg>'''
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=60", "Access-Control-Allow-Origin": "*"})
