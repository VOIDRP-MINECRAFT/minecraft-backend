"""Public feed of our plugin builds: what came out, for which cores and Minecraft versions.

* ``GET /integration/releases`` — JSON (latest 50 stable builds; ``?plugin=voidrp-perms``,
  ``?beta=1`` adds betas). Open to any site (CORS ``*``).
* ``GET /integration/releases.rss`` — the same as RSS 2.0: partners subscribe in a reader,
  a Discord bot or Telegram (e.g. via an RSS bot) and hear about builds without our panel.

Yanked builds never appear; file paths and hashes stay private (downloads go through the panel
and the update script, which check the server's secret).
"""
from __future__ import annotations

from email.utils import format_datetime
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import integration_catalog as cat
from apps.api.app.db import get_db_session
from apps.api.app.models.plugin_release import PluginRelease

router = APIRouter(prefix="/integration", tags=["integration"])
_Db = Annotated[Session, Depends(get_db_session)]
ORG = "https://github.com/VOIDRP-MINECRAFT"


def _rows(session: Session, plugin: str | None, beta: bool, limit: int = 50) -> list[PluginRelease]:
    q = select(PluginRelease).where(PluginRelease.yanked.is_(False))
    if not beta:
        q = q.where(PluginRelease.channel == "stable")
    if plugin:
        q = q.where(PluginRelease.plugin == plugin)
    return list(session.scalars(q.order_by(PluginRelease.published_at.desc()).limit(limit)).all())


def _view(r: PluginRelease) -> dict:
    entry = cat.entry(r.plugin) or {}
    repo = entry.get("repo")
    return {
        "plugin": r.plugin, "name": entry.get("name") or r.plugin, "version": r.version, "channel": r.channel,
        "important": r.important, "recommended": r.recommended,
        "platforms": r.platforms or [], "mc_versions": r.mc_versions or [],
        "changelog": r.changelog, "published_at": r.published_at.isoformat(), "size": r.size,
        "url": f"{ORG}/{repo}/releases/tag/v{r.version}" if repo else None,
    }


@router.get("/releases")
def releases(session: _Db, plugin: str | None = Query(None, max_length=64), beta: bool = False) -> JSONResponse:
    return JSONResponse({"releases": [_view(r) for r in _rows(session, plugin, beta)]},
                        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


@router.get("/releases.rss")
def releases_rss(session: _Db, plugin: str | None = Query(None, max_length=64), beta: bool = False) -> Response:
    api = get_settings().public_api_url.rstrip("/")
    site = (get_settings().website_base_url or "https://void-rp.ru").rstrip("/")
    items = []
    for r in _rows(session, plugin, beta):
        v = _view(r)
        title = f"{v['name']} {v['version']}" + (" — важное обновление" if v["important"] else "") + (" (бета)" if v["channel"] != "stable" else "")
        body = (f"<p><b>{escape(v['name'])} {escape(v['version'])}</b> · ядра: {escape(', '.join(v['platforms']) or '—')}"
                f" · Minecraft: {escape(', '.join(v['mc_versions']) or 'любой')}</p>"
                f"<pre>{escape(v['changelog'] or 'Без описания изменений.')}</pre>"
                f"<p>Обновить: «Интеграция» в панели VoidRP или <code>curl -fsSL {api}/api/v1/integration/voidrp-update.sh | bash</code></p>")
        link = v["url"] or f"{site}/partners"
        items.append(
            f"<item><title>{escape(title)}</title><link>{escape(link)}</link>"
            f"<guid isPermaLink=\"false\">voidrp-{escape(r.plugin)}-{escape(r.version)}</guid>"
            f"<pubDate>{format_datetime(r.published_at)}</pubDate>"
            f"<category>{escape(v['name'])}</category>"
            f"<description>{escape(body)}</description></item>")
    self_url = f"{api}/api/v1/integration/releases.rss"
    xml = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
           "<rss version=\"2.0\" xmlns:atom=\"http://www.w3.org/2005/Atom\"><channel>"
           "<title>VoidRP — сборки плагинов</title>"
           f"<link>{site}/partners</link>"
           f"<atom:link href=\"{escape(self_url)}\" rel=\"self\" type=\"application/rss+xml\"/>"
           "<description>Новые версии VoidRpAuth, VoidRpPerms, VoidRpGuard и других плагинов VoidRP</description>"
           "<language>ru</language>" + "".join(items) + "</channel></rss>")
    return Response(xml, media_type="application/rss+xml; charset=utf-8",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})
