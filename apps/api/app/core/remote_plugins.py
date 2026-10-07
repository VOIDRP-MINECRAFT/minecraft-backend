"""Plugins of a partner's server, through its VoidRpPerms (modules.files).

The list: the jars in plugins/, plugins/disabled/ and plugins/update/ (file jobs) with names
and versions from the plugin's inventory (heartbeat). Changes are made on the spot and take
effect at the next restart, as Paper reads plugins only at start:
- a new version with the same file name → plugins/update/<file> (Paper swaps it in at start);
- a new version under another name → the new jar into plugins/, the old one into the trash;
- a new plugin → plugins/<file>;
- off / on → plugins/disabled/ and back; remove → plugins/.voidrp-trash/.
Uploaded jars are checked here (plugin.yml) and fetched by the plugin from a blob.
"""
from __future__ import annotations

import os
import re
import time

from sqlalchemy.orm import Session

from apps.api.app.core import integration_updates, remote_files
from apps.api.app.core.remote_files import RemoteFileError
from apps.api.app.models.game_server import GameServer
from apps.api.app.services import remote_file_store as rfs

TRASH = "plugins/.voidrp-trash"
AFTER_RESTART = "применится после перезапуска сервера"


def _jars(server: GameServer, folder: str) -> list[dict]:
    try:
        entries = rfs.listing(server, folder)
    except RemoteFileError as exc:
        if exc.status == 404:
            return []
        raise
    return [e for e in entries if e["type"] == "file" and e["name"].lower().endswith(".jar")]


def _guess_name(filename: str) -> str:
    base = re.sub(r"\.jar$", "", filename, flags=re.I)
    return re.split(r"[-_ ](?=v?\d)", base, maxsplit=1)[0] or base


def list_plugins(session: Session, server: GameServer) -> dict:
    inv = integration_updates.inventory(server) or {}
    by_file = {p.get("file"): p for p in inv.get("plugins") or [] if p.get("file")}
    top = rfs.listing(server, "plugins")
    folders = {e["name"] for e in top if e["type"] == "dir"}

    def item(e: dict, loaded: bool) -> dict:
        p = by_file.get(e["name"]) if loaded else None
        name = (p or {}).get("name") or _guess_name(e["name"])
        return {
            "filename": e["name"], "size": e["size"], "name": name, "version": (p or {}).get("version") or "",
            "authors": [], "description": "", "depend": [], "softdepend": [], "paper": False, "api_version": "",
            "loaded": bool(p and p.get("enabled", True)), "known": p is not None,
            "config_folder": f"plugins/{name}" if loaded and name in folders else None,
        }

    enabled = [item(e, True) for e in top if e["type"] == "file" and e["name"].lower().endswith(".jar")]
    return {
        "available": True,
        "remote": True,
        "note": "Изменения начнут работать после перезапуска сервера.",
        "plugman": {"installed": False, "name": None},
        "enabled": enabled,
        "disabled": [item(e, False) for e in _jars(server, "plugins/disabled")],
        "updates": [item(e, False) for e in _jars(server, "plugins/update")],
        "running": True,
    }


def _trash_name(filename: str) -> str:
    return f"{TRASH}/{int(time.time())}-{filename}"


def apply_staged(server: GameServer, staging_dir: str, filenames: list[str], installed: dict, read_meta, sanitize) -> list[dict]:
    """Installs the chosen staged jars on the partner's server (see the module doc)."""
    enabled_files = {p["filename"] for p in installed["enabled"]}
    by_name = {p["name"].lower(): p for p in installed["enabled"] + installed["disabled"] if p.get("name")}
    done = []
    for fname in filenames:
        base = sanitize(fname)
        src = os.path.join(staging_dir, base)
        if not os.path.isfile(src):
            raise RemoteFileError(f"Файл не найден в загрузке: {base}", 400)
        meta = read_meta(src)
        if meta.get("error"):
            raise RemoteFileError(f"{base}: {meta['error']}", 400)
        with open(src, "rb") as fh:
            data = fh.read()
        blob = remote_files.put_blob(server, data, base)
        old = by_name.get(meta["name"].lower())
        was_on = bool(old) and old["filename"] in enabled_files
        if old and old["filename"] == base and was_on:
            target = f"plugins/update/{base}"     # Paper swaps a same-named jar in at start
        else:
            target = f"plugins/{base}"
        label = (f"{meta['name']} {old.get('version') or ''} → {meta['version']}" if old
                 else f"{meta['name']} {meta['version']} (новый)")
        remote_files.call(server, "fetch", timeout=120.0, url=blob["url"], path=target, sha256=blob["sha256"])
        if old and (old["filename"] != base or not was_on):
            where = "plugins" if was_on else "plugins/disabled"
            remote_files.call(server, "rename", path=f"{where}/{old['filename']}", to=_trash_name(old["filename"]))
        done.append({"filename": base, "status": "applied", "label": label, "result": AFTER_RESTART})
    return done


def change(server: GameServer, filename: str, op: str) -> dict:
    name = rfs.norm(filename)
    if "/" in name or not name.lower().endswith(".jar"):
        raise RemoteFileError("Некорректное имя файла", 400)
    if op == "disable":
        remote_files.call(server, "rename", path=f"plugins/{name}", to=f"plugins/disabled/{name}")
    elif op == "enable":
        remote_files.call(server, "rename", path=f"plugins/disabled/{name}", to=f"plugins/{name}")
    elif op == "remove":
        src = f"plugins/{name}" if rfs.stat(server, f"plugins/{name}") else f"plugins/disabled/{name}"
        remote_files.call(server, "rename", path=src, to=_trash_name(name))
    else:
        raise RemoteFileError("Неизвестное действие", 400)
    return {"status": "applied", "result": AFTER_RESTART}
