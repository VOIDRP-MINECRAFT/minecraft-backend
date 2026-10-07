"""Files of a partner's server through its VoidRpPerms (modules.files, 0.8.0+).

The plugin polls ``/game-sync/files/pending`` every couple of seconds, does each job inside
the server folder on its own thread and posts the result. Here a job is queued and waited
for (a few seconds; the plugin answers in ~2–3 s). Content travels base64 in pieces of
1 MiB: a big file is read or written piece by piece; a write lands in a part file on the
server and replaces the target only on the last piece (size and SHA-256 checked there).

Plugin jars the admin uploads are not pushed piece by piece: they are kept here as a blob
for a day and the plugin downloads it (``fetch``) from ``/game-sync/files/blob/{id}`` with
its own secret.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core.security import utc_now
from apps.api.app.db import SessionLocal
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_file_job import ServerFileJob

CHUNK = 1024 * 1024
MAX_FILE = 300 * 1024 * 1024
PENDING_TTL_SECONDS = 60
KEEP_DONE_MINUTES = 10
BLOB_TTL_HOURS = 24


class RemoteFileError(OSError):
    """The plugin refused or did not answer: the message is for the admin, status is HTTP-like."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def call(server: GameServer, op: str, timeout: float = 15.0, **args: Any) -> dict[str, Any]:
    """Queues one job for the server's plugin and waits for its result."""
    with SessionLocal() as session:
        row = ServerFileJob(server_id=server.id, op=op, args=args, status="pending")
        session.add(row)
        session.commit()
        job_id = row.id
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        time.sleep(0.2)
        with SessionLocal() as session:
            row = session.get(ServerFileJob, job_id)
            if row is not None and row.status in ("done", "failed"):
                if row.status == "failed":
                    raise RemoteFileError(row.error or "сервер отказал", row.http_status or 502)
                return row.result or {}
    with SessionLocal() as session:
        # Still not taken: drop it so it does not run later out of the blue.
        session.execute(update(ServerFileJob).where(ServerFileJob.id == job_id, ServerFileJob.status == "pending")
                        .values(status="expired", done_at=utc_now()))
        session.commit()
        row = session.get(ServerFileJob, job_id)
        taken = row is not None and row.status == "sent"
    if taken:
        raise RemoteFileError("Сервер принял действие, но не ответил вовремя — обновите страницу через пару секунд", 504)
    raise RemoteFileError("Сервер не отвечает: плагин VoidRpPerms не забирает задания (выключен модуль files или нет связи)", 504)


def take_pending(session: Session, server: GameServer, limit: int = 10) -> list[ServerFileJob]:
    """Jobs for the plugin to do now; marked sent so they run once. Old results are cleaned."""
    now = utc_now()
    session.execute(update(ServerFileJob).where(
        ServerFileJob.server_id == server.id, ServerFileJob.status == "pending",
        ServerFileJob.created_at < now - timedelta(seconds=PENDING_TTL_SECONDS)).values(status="expired", done_at=now))
    # results carry file contents: keep them only as long as anyone could be waiting
    session.execute(delete(ServerFileJob).where(
        ServerFileJob.server_id == server.id, ServerFileJob.created_at < now - timedelta(minutes=KEEP_DONE_MINUTES)))
    rows = list(session.scalars(select(ServerFileJob).where(
        ServerFileJob.server_id == server.id, ServerFileJob.status == "pending")
        .order_by(ServerFileJob.id).limit(limit).with_for_update(skip_locked=True)).all())
    for r in rows:
        r.status = "sent"
    session.commit()
    return rows


def finish(session: Session, server: GameServer, job_id: int, ok: bool, result: dict | None,
           error: str | None, status: int | None) -> bool:
    row = session.get(ServerFileJob, job_id)
    if row is None or row.server_id != server.id:
        return False
    row.status = "done" if ok else "failed"
    row.result = result if ok else None
    row.error = None if ok else (error or "ошибка")[:2000]
    row.http_status = status
    row.done_at = utc_now()
    # the piece that was sent is no longer needed
    if row.op == "write" and isinstance(row.args, dict) and "data" in row.args:
        row.args = {k: v for k, v in row.args.items() if k != "data"}
    session.commit()
    return True


# ── whole files ──────────────────────────────────────────────────────────────

def read_all(server: GameServer, rel: str, limit: int = MAX_FILE) -> tuple[bytes, dict]:
    """The whole file (piece by piece) and the last read's meta (size, mtime)."""
    out = bytearray()
    meta: dict = {}
    offset = 0
    while True:
        r = call(server, "read", path=rel, offset=offset, length=CHUNK)
        piece = base64.b64decode(r.get("data") or "")
        out += piece
        meta = r
        if len(out) > limit:
            raise RemoteFileError("Файл слишком большой", 413)
        offset += len(piece)
        if r.get("eof") or not piece:
            break
    return bytes(out), meta


def write_all(server: GameServer, rel: str, data: bytes, *, create: bool = False) -> dict:
    """Writes the whole file in pieces; the server swaps it in after the last one."""
    if len(data) > MAX_FILE:
        raise RemoteFileError("Файл больше 300 МБ", 413)
    sha = hashlib.sha256(data).hexdigest()
    offset = 0
    result: dict = {}
    while True:
        piece = data[offset:offset + CHUNK]
        final = offset + len(piece) >= len(data)
        args: dict[str, Any] = {"path": rel, "offset": offset, "data": base64.b64encode(piece).decode(), "final": final}
        if create:
            args["create"] = True
        if final:
            args["size"] = len(data)
            args["sha256"] = sha
        result = call(server, "write", timeout=30.0, **args)
        offset += len(piece)
        if final:
            return result


# ── blobs: uploaded jars the plugin downloads itself ─────────────────────────

def _blob_dir() -> Path:
    d = Path(get_settings().releases_dir).parent / "voidrp_remote_blobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def put_blob(server: GameServer, data: bytes, name: str) -> dict:
    """Keeps an upload for the plugin to fetch; returns {id, url, sha256}."""
    _prune_blobs()
    blob_id = uuid.uuid4().hex
    d = _blob_dir()
    (d / f"{blob_id}.bin").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    (d / f"{blob_id}.json").write_text(json.dumps({"server_id": str(server.id), "name": name, "sha256": sha,
                                                   "size": len(data), "at": time.time()}))
    return {"id": blob_id, "url": f"/game-sync/files/blob/{blob_id}", "sha256": sha}


def blob_path(server: GameServer, blob_id: str) -> Path | None:
    """The blob for this server (a server never gets another one's upload)."""
    if not blob_id.isalnum() or len(blob_id) != 32:
        return None
    d = _blob_dir()
    try:
        meta = json.loads((d / f"{blob_id}.json").read_text())
    except (OSError, ValueError):
        return None
    if meta.get("server_id") != str(server.id):
        return None
    p = d / f"{blob_id}.bin"
    return p if p.exists() else None


def _prune_blobs() -> None:
    cutoff = time.time() - BLOB_TTL_HOURS * 3600
    for p in _blob_dir().glob("*.bin"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                p.with_suffix(".json").unlink(missing_ok=True)
        except OSError:
            pass
