"""Every change made through the admin panel lands in the audit log.

Endpoints that know what they changed write their own row with ``record_audit`` (a kick,
a ban, a price, a rollback). Many did not — moderators, servers, mods, the launcher, the
market… — so this middleware writes a generic row for any POST/PUT/PATCH/DELETE under
``/api/v1/admin/`` that did not: who, which endpoint, on which server, the answer's
status and the request body with passwords and secrets masked. Denied attempts (401/403)
are written too — someone trying what they may not is worth knowing.

A plain ASGI middleware, so the request body is passed through untouched as it is read.
Best-effort like ``record_audit``: nothing here can fail the request.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from apps.api.app.core.audit import audit_marker, record_audit

logger = logging.getLogger(__name__)

_PREFIX = "/api/v1/admin/"
_WRITES = {"POST", "PUT", "PATCH", "DELETE"}
_SECRET_WORDS = ("password", "secret", "token", "api_key", "apikey")
_BODY_LIMIT = 4000


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if any(w in str(k).lower() for w in _SECRET_WORDS) else _mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value[:50]]
    return value


class AdminWriteAuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") not in _WRITES or not scope.get("path", "").startswith(_PREFIX):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        size = 0
        status = {"code": 0}
        marker: dict = {"done": False}
        token = audit_marker.set(marker)

        async def receive_tee():
            nonlocal size
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                if size < _BODY_LIMIT:
                    chunks.append(body[: _BODY_LIMIT - size])
                size += len(body)
            return message

        async def send_tee(message):
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive_tee, send_tee)
        finally:
            audit_marker.reset(token)
            if not marker["done"]:
                try:
                    self._write(scope, b"".join(chunks), size, status["code"])
                except Exception:  # noqa: BLE001 — auditing must never break the request
                    logger.exception("admin write audit failed for %s", scope.get("path"))

    def _write(self, scope, body: bytes, size: int, code: int) -> None:
        from apps.api.app.core.security import decode_access_token
        from apps.api.app.db import SessionLocal
        from apps.api.app.models.game_server import GameServer
        from apps.api.app.models.user import User

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        query = scope.get("query_string", b"").decode("latin-1")
        route = scope.get("route")
        template = getattr(route, "path", None) or scope.get("path", "")
        endpoint = getattr(getattr(route, "endpoint", None), "__module__", "") or ""
        category = endpoint.rsplit(".", 1)[-1].removeprefix("admin_") or "admin"

        payload: Any = None
        if body:
            try:
                payload = _mask(json.loads(body))
            except (ValueError, UnicodeDecodeError):
                payload = f"<{size} байт, не JSON>"
        slug = None
        for part in query.split("&"):
            if part.startswith("server="):
                slug = part.split("=", 1)[1]
        slug = slug or headers.get("x-server-slug")

        session = SessionLocal()
        try:
            actor = None
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                try:
                    actor = session.get(User, UUID(decode_access_token(auth[7:])["sub"]))
                except Exception:  # noqa: BLE001 — a bad token is still an attempt worth logging
                    actor = None
            server_id = None
            if slug:
                server = session.query(GameServer).filter(GameServer.slug == slug).one_or_none()
                server_id = server.id if server else None
            path = scope.get("path", "")
            record_audit(
                session,
                category=category[:48],
                action=f"{scope.get('method')} {template}"[:64],
                actor=actor,
                target_type="endpoint",
                target_id=path[:120],
                target_label=(f"отказано ({code})" if code in (401, 403) else f"ответ {code}"),
                server_id=server_id,
                meta={"status": code, "path": path, "query": query or None, "body": payload,
                      "generic": True},
                ip=(headers.get("x-forwarded-for", "").split(",")[0].strip() or
                    (scope.get("client") or [None])[0]),
            )
        finally:
            session.close()
