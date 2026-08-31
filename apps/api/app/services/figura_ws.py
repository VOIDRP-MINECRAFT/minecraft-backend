"""In-memory hub for the Figura backend WebSocket.

Single-process (the prod backend runs one uvicorn worker). Tracks each connected player's
socket and their subscriptions, and fans out S2C EVENT messages so subscribers re-fetch a
changed avatar over HTTP. See ``docs/figura_backend_spec.md``.
"""
from __future__ import annotations

import asyncio
import struct
from uuid import UUID

from starlette.websockets import WebSocket

# S2C message ids
S2C_AUTH = 0
S2C_PING = 1
S2C_EVENT = 2


def _uuid_bytes(uuid_str: str) -> bytes:
    return UUID(uuid_str).bytes   # 16 bytes, big-endian (msb, lsb) — matches Java UUID(long, long)


class FiguraHub:
    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}                 # owner uuid -> socket
        self._subs: dict[str, set[str]] = {}                     # target uuid -> subscriber uuids
        self._lock = asyncio.Lock()

    async def register(self, uuid: str, ws: WebSocket) -> None:
        async with self._lock:
            old = self._sockets.get(uuid)
            self._sockets[uuid] = ws
        if old is not None and old is not ws:
            try:
                await old.close()
            except Exception:  # noqa: BLE001
                pass

    async def unregister(self, uuid: str, ws: WebSocket) -> None:
        async with self._lock:
            if self._sockets.get(uuid) is ws:
                del self._sockets[uuid]
            for subs in self._subs.values():
                subs.discard(uuid)

    async def subscribe(self, subscriber: str, target: str) -> None:
        async with self._lock:
            self._subs.setdefault(target, set()).add(subscriber)

    async def unsubscribe(self, subscriber: str, target: str) -> None:
        async with self._lock:
            if target in self._subs:
                self._subs[target].discard(subscriber)

    async def send_auth(self, ws: WebSocket) -> None:
        await ws.send_bytes(bytes([S2C_AUTH]))

    async def notify_event(self, target_uuid: str) -> None:
        """Tell everyone subscribed to ``target_uuid`` (and the owner) to reload that avatar."""
        target_uuid = str(target_uuid)
        async with self._lock:
            receivers = set(self._subs.get(target_uuid, set()))
            receivers.add(target_uuid)   # the owner re-fetches their own too
            sockets = [self._sockets[u] for u in receivers if u in self._sockets]
        payload = bytes([S2C_EVENT]) + _uuid_bytes(target_uuid)
        await asyncio.gather(*(self._safe_send(s, payload) for s in sockets), return_exceptions=True)

    async def relay_ping(self, sender_uuid: str, ping_id: int, sync: int, data: bytes) -> None:
        async with self._lock:
            receivers = [self._sockets[u] for u in self._subs.get(sender_uuid, set()) if u in self._sockets]
        payload = bytes([S2C_PING]) + _uuid_bytes(sender_uuid) + struct.pack(">i", ping_id) + bytes([sync & 0xFF]) + data
        await asyncio.gather(*(self._safe_send(s, payload) for s in receivers), return_exceptions=True)

    @staticmethod
    async def _safe_send(ws: WebSocket, payload: bytes) -> None:
        try:
            await ws.send_bytes(payload)
        except Exception:  # noqa: BLE001 — a dead socket is cleaned up on its own disconnect
            pass


hub = FiguraHub()


def notify_event_threadsafe(target_uuid: str) -> None:
    """Fire a WS EVENT from sync code (HTTP handlers). Best-effort; safe if no loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(hub.notify_event(target_uuid))
