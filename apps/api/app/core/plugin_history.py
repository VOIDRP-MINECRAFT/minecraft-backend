"""Earlier versions of a server's plugins, and putting one back.

A replaced or removed jar never disappears, it goes to a trash:
- our servers: ``<OPS_BASE>/trash/<slug>/plugins/<YYYYmmdd-HHMMSS>/<file>`` (mod_ops._trash) — name
  and version are read from the jar itself;
- a partner's server: ``plugins/.voidrp-trash/<unix>-<file>`` on their machine. Name and version are
  remembered here when the jar is moved (``<OPS_BASE>/plugin_history/<slug>.json``); older entries
  get a name guessed from the file name.

Rolling back moves the current version to the trash (so it can be put back in turn) and the chosen
one into its place: on a partner's server at once (through PlugMan when it runs, see
core/remote_plugins.py), on ours through the same change queue as an upload.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.app.core import mod_ops, server_changes
from apps.api.app.models.game_server import GameServer

HISTORY_DIR = os.path.join(mod_ops.OPS_BASE, "plugin_history")
_LOCAL_ID = re.compile(r"^\d{8}-\d{6}/[^/\\]+\.jar$", re.I)
_REMOTE_ID = re.compile(r"^(\d{9,11})-([^/\\]+\.jar)$", re.I)


class HistoryError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ── what a partner's trash holds (kept here, their trash has only the files) ─

def _path(slug: str) -> str:
    return os.path.join(HISTORY_DIR, f"{slug}.json")


def _update(slug: str, fn) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(_path(slug) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(_path(slug)) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        fn(data)
        tmp = _path(slug) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, _path(slug))


def remember(server: GameServer, trash_name: str, *, name: str | None, version: str | None) -> None:
    """A jar just went to a partner's trash as ``trash_name`` (the file name inside it)."""
    def put(data: dict) -> None:
        data[trash_name] = {"name": name or "", "version": version or ""}
    _update(server.slug, put)


def forget(server: GameServer, trash_name: str) -> None:
    _update(server.slug, lambda data: data.pop(trash_name, None))


def _remembered(server: GameServer) -> dict:
    try:
        with open(_path(server.slug)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# ── listing ──────────────────────────────────────────────────────────────────

def _same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.lower() == b.lower()


def _current_of(installed: dict, name: str, filename: str) -> dict | None:
    """The installed plugin a trashed version belongs to: by name, else by file name stem."""
    every = installed.get("enabled", []) + installed.get("disabled", [])
    hit = next((p for p in every if _same(p.get("name"), name)), None)
    if hit:
        return hit
    stem = re.split(r"[-_ ](?=v?\d)", filename[:-4], maxsplit=1)[0].lower()
    return next((p for p in every if p["filename"].lower().startswith(stem) or _same(p.get("name"), stem)), None)


def _local_versions(server: GameServer) -> list[dict]:
    from apps.api.app.core.plugin_ops import read_meta

    root = os.path.join(mod_ops.OPS_BASE, "trash", server.slug, "plugins")
    out = []
    if not os.path.isdir(root):
        return out
    for ts in os.listdir(root):
        d = os.path.join(root, ts)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            path = os.path.join(d, f)
            if not (f.lower().endswith(".jar") and os.path.isfile(path)):
                continue
            meta = read_meta(path)
            if meta.get("error"):
                continue
            try:
                at = datetime.strptime(ts, "%Y%m%d-%H%M%S").astimezone(timezone.utc).isoformat()
            except ValueError:
                at = None
            out.append({"id": f"{ts}/{f}", "filename": f, "name": meta["name"], "version": meta["version"],
                        "size": os.path.getsize(path), "at": at, "known": True})
    return out


def _remote_versions(server: GameServer) -> list[dict]:
    from apps.api.app.core import remote_plugins
    from apps.api.app.core.remote_files import RemoteFileError
    from apps.api.app.services import remote_file_store as rfs

    try:
        entries = rfs.listing(server, remote_plugins.TRASH)
    except RemoteFileError as exc:
        if exc.status == 404:
            return []
        raise
    known = _remembered(server)
    out = []
    for e in entries:
        m = _REMOTE_ID.match(e["name"]) if e["type"] == "file" else None
        if not m:
            continue
        rec = known.get(e["name"]) or {}
        filename = m.group(2)
        out.append({"id": e["name"], "filename": filename,
                    "name": rec.get("name") or remote_plugins._guess_name(filename), "version": rec.get("version") or "",
                    "size": e["size"], "at": datetime.fromtimestamp(int(m.group(1)), timezone.utc).isoformat(),
                    "known": bool(rec.get("name"))})
    return out


def versions(session: Session, server: GameServer) -> dict:
    """Earlier versions in the trash, newest first, each tied to the plugin installed now
    (``current``: its file name, or None when the plugin is gone). A copy of the version
    that is installed right now is left out."""
    from apps.api.app.core import plugin_ops
    from apps.api.app.services import remote_file_store as rfs

    installed = plugin_ops.list_plugins(session, server)
    if not installed.get("available"):
        return {"versions": []}
    rows = _remote_versions(server) if rfs.is_remote(server) else _local_versions(server)
    out = []
    for r in rows:
        cur = _current_of(installed, r["name"], r["filename"])
        if cur and cur.get("version") and r["version"] and cur["version"] == r["version"] and _same(cur.get("name"), r["name"]):
            continue
        if cur and not r["known"]:
            r["name"] = cur.get("name") or r["name"]
        r["current"] = cur["filename"] if cur else None
        r["current_version"] = (cur or {}).get("version") or ""
        out.append(r)
    out.sort(key=lambda r: r["at"] or "", reverse=True)
    return {"versions": out}


# ── rolling back ─────────────────────────────────────────────────────────────

def rollback(session: Session, server: GameServer, version_id: str, created_by: str | None) -> dict:
    """Puts an earlier version back. Returns {status, result, label} like the other plugin actions."""
    from apps.api.app.core import plugin_ops
    from apps.api.app.services import remote_file_store as rfs

    found = next((v for v in versions(session, server)["versions"] if v["id"] == version_id), None)
    if found is None:
        raise HistoryError("Эта версия не найдена в корзине — обновите список", 404)
    installed = plugin_ops.list_plugins(session, server)
    cur = _current_of(installed, found["name"], found["filename"])
    label = f"{found['name']} {(cur or {}).get('version') or '—'} → {found['version'] or found['filename']}"
    if rfs.is_remote(server):
        from apps.api.app.core import remote_plugins

        out = remote_plugins.rollback(server, found, cur, installed)
        return {**out, "label": label}

    if not _LOCAL_ID.match(version_id):
        raise HistoryError("Некорректная версия")
    src = os.path.join(mod_ops.OPS_BASE, "trash", server.slug, "plugins", version_id)
    filename = found["filename"]
    if cur and cur["filename"] != filename and any(p["filename"] == filename for p in installed["enabled"] + installed["disabled"]):
        raise HistoryError(f"Файл {filename} уже занят другим плагином")
    change = server_changes.queue(
        session, server, kind="plugin", op="add", filename=filename,
        source_path=server_changes.keep_source(server, src, filename), replaces=cur["filename"] if cur else None,
        label=f"откат {label}", created_by=created_by,
    )
    return {"status": change.status, "result": change.result, "label": label}
