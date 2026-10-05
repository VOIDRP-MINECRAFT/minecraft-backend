"""Can players reach the server? The backend pings its public address from outside.

The address is the one players connect to (``host``/``port`` of the server row), so a closed
port, a wrong DNS record or a firewall shows up even while the plugins report fine. Cached a
minute in Redis.
"""
from __future__ import annotations

import time
from typing import Any

from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.services.redis_cache_service import RedisCacheService

TTL = 60


def check(server: GameServer, fresh: bool = False) -> dict[str, Any]:
    host, port = (server.host or "").strip(), int(server.port or 25565)
    if not host:
        return {"ok": False, "address": None, "error": "адрес сервера не указан"}
    cache = RedisCacheService()
    key = f"integration_reach:{server.id}:{host}:{port}"
    if not fresh:
        cached = cache.get_json(key)
        if cached:
            return cached
    out: dict[str, Any] = {"address": f"{host}:{port}", "checked_at": utc_now().isoformat()}
    try:
        from mcstatus import JavaServer  # type: ignore[import-untyped]

        t0 = time.monotonic()
        st = JavaServer.lookup(f"{host}:{port}", timeout=4).status()
        out.update(ok=True, latency_ms=int((time.monotonic() - t0) * 1000),
                   version=st.version.name, protocol=st.version.protocol,
                   players=st.players.online, max=st.players.max,
                   motd=(st.motd.to_plain() if hasattr(st.motd, "to_plain") else str(st.description))[:160])
    except Exception as exc:  # noqa: BLE001 — any failure is "not reachable", with its reason
        reason = type(exc).__name__
        text = str(exc)
        if "timed out" in text.lower() or reason in ("TimeoutError", "timeout"):
            why = "не отвечает (таймаут) — порт закрыт фаерволом или сервер выключен"
        elif "refused" in text.lower():
            why = "соединение отклонено — на этом порту ничего не слушает"
        elif "Name or service not known" in text or "getaddrinfo" in text or "nodename" in text:
            why = f"адрес {host} не находится в DNS"
        else:
            why = f"{reason}: {text[:120]}"
        out.update(ok=False, error=why)
    cache.set_json(key, out, ttl_seconds=TTL)
    return out
