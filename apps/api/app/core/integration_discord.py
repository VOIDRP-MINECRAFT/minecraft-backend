"""The same integration notices as in Telegram, into the partner's Discord channel.

The server's owner puts a webhook URL in «Интеграция» → «Обновления»
(``game_servers.integration_settings.discord_webhook``). Each event goes out once per server
(Redis remembers what was posted); a webhook that fails never stops anything else.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from apps.api.app.config import get_settings
from apps.api.app.models.game_server import GameServer
from apps.api.app.services.redis_cache_service import RedisCacheService

log = logging.getLogger(__name__)

WEBHOOK = re.compile(r"^https://(?:canary\.|ptb\.)?(?:discord|discordapp)\.com/api/webhooks/\d+/[\w-]+$")
COLORS = {"ok": 0x22C55E, "warn": 0xF59E0B, "err": 0xEF4444, "info": 0x8B5CF6}


def webhook_of(server: GameServer) -> str | None:
    url = ((server.integration_settings or {}).get("discord_webhook") or "").strip()
    return url if WEBHOOK.match(url) else None


def _page(server: GameServer) -> str:
    return f"{(get_settings().website_base_url or 'https://void-rp.ru').rstrip('/')}/admin/integration?server={server.slug}"


def post(url: str, title: str, description: str, color: str = "info", fields: list[dict] | None = None,
         link: str | None = None) -> bool:
    from apps.api.app.services.news_service import _http_post_json

    embed: dict[str, Any] = {"title": title[:256], "description": description[:4000], "color": COLORS.get(color, COLORS["info"]),
                             "footer": {"text": "VoidRP · Интеграция"}}
    if fields:
        embed["fields"] = fields[:20]
    if link:
        embed["url"] = link
    return _http_post_json(url, {"username": "VoidRP", "embeds": [embed]}, timeout=8.0)


def _once(server: GameServer, key: str) -> bool:
    cache = RedisCacheService()
    k = f"discord_posted:{server.id}:{key}"
    if cache.get_json(k):
        return False
    cache.set_json(k, {"at": 1}, ttl_seconds=60 * 24 * 3600)
    return True


def incident(server: GameServer, event: str, inc) -> None:
    url = webhook_of(server)
    if not url or not _once(server, f"inc:{inc.id}:{event}"):
        return
    try:
        if event == "down":
            post(url, f"🔴 {server.name}: сервер недоступен", f"{inc.detail or 'не отвечает'} с {inc.started_at:%H:%M} UTC.",
                 "err", link=_page(server))
        elif event == "up":
            minutes = max(1, int((inc.ended_at - inc.started_at).total_seconds() // 60))
            post(url, f"🟢 {server.name}: снова на связи", f"Простой — {minutes} мин.", "ok", link=_page(server))
        elif event == "tps_low":
            post(url, f"🟠 {server.name}: сервер тормозит", inc.detail or "TPS ниже нормы", "warn", link=_page(server))
        else:
            post(url, f"🟢 {server.name}: TPS в норме", "Просадка закончилась.", "ok", link=_page(server))
    except Exception:  # noqa: BLE001 — Discord must never break the watch
        log.exception("Discord webhook of %s failed", server.slug)


def releases(server: GameServer, updates: list[tuple[dict, Any, str | None]]) -> None:
    url = webhook_of(server)
    if not url:
        return
    fresh = [u for u in updates if _once(server, f"rel:{u[1].id}")]
    if not fresh:
        return
    fields = []
    for entry, row, installed in fresh:
        value = (row.changelog or "Без описания.")[:900]
        fields.append({"name": f"{entry['name']}: {installed or '—'} → {row.version}{' ❗' if row.important else ''}",
                       "value": value})
    important = any(r.important for _, r, _ in fresh)
    try:
        post(url, f"{'❗ Важные обновления' if important else '🆕 Обновления'} плагинов VoidRP — {server.name}",
             "Сборки и конфиги — в «Интеграции». Paper подменит jar при перезапуске, если положить его в "
             "`plugins/update/`, или включите автообновление.", "err" if important else "info", fields, link=_page(server))
    except Exception:  # noqa: BLE001
        log.exception("Discord webhook of %s failed", server.slug)


def secret(server: GameServer, text: str) -> None:
    url = webhook_of(server)
    if not url:
        return
    try:
        post(url, f"🔑 {server.name}: секрет сервера сменён", text, "warn", link=_page(server))
    except Exception:  # noqa: BLE001
        log.exception("Discord webhook of %s failed", server.slug)


def test(server: GameServer, url: str) -> bool:
    return post(url, f"✅ {server.name}: вебхук VoidRP подключён",
                "Сюда будут приходить новые версии плагинов VoidRP, сбои и восстановление сервера.", "ok",
                link=_page(server))
