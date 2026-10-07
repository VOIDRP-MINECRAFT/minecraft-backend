"""Plugins of a partner's server, through its VoidRpPerms (modules.files).

The list: the jars in plugins/, plugins/disabled/ and plugins/update/ (file jobs) with names
and versions from the plugin's inventory (heartbeat). Changes are made on the spot and take
effect at the next restart, as Paper reads plugins only at start:
- a new version with the same file name → plugins/update/<file> (Paper swaps it in at start);
- a new version under another name → the new jar into plugins/, the old one into the trash;
- a new plugin → plugins/<file>;
- off / on → plugins/disabled/ and back; remove → plugins/.voidrp-trash/.
Uploaded jars are checked here (plugin.yml) and fetched by the plugin from a blob.

With PlugMan(X) on the server every change is applied at once through the plugin's console
(the same queue as the admin's console): a new plugin is loaded, a new version replaces the
old one (unload, swap the jar, load), off/remove unload, on loads. Its answers come back with
the result; without PlugMan everything waits for the restart.

Every jar moved to the trash is remembered (name, version) for «Версии» and rollback()
(core/plugin_history.py).
"""
from __future__ import annotations

import os
import re
import time

from sqlalchemy.orm import Session

from apps.api.app.core import integration_updates, remote_files, server_console
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


def _plugman(server: GameServer) -> str | None:
    """PlugMan's name if the server runs it (from the plugin's inventory)."""
    inv = integration_updates.inventory(server) or {}
    for p in inv.get("plugins") or []:
        if (p.get("name") or "").lower() in ("plugmanx", "plugman") and p.get("enabled", True):
            return p["name"]
    return None


def _loaded_name(server: GameServer, filename: str) -> str | None:
    inv = integration_updates.inventory(server) or {}
    for p in inv.get("plugins") or []:
        if p.get("file") == filename and p.get("enabled", True):
            return p.get("name")
    return None


def _console(server: GameServer, command: str) -> str:
    from apps.api.app.core.server_ops import strip_color_codes

    try:
        out = server_console.run(server, command, timeout=25.0)
    except OSError as exc:
        out = f"ошибка: {exc}"
    out = strip_color_codes(out or "").strip().replace("[PlugMan] ", "")
    return f"{command} → {out[:200] or 'ок'}"


def _stem(filename: str) -> str:
    return re.sub(r"\.jar$", "", filename, flags=re.I)


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
    plugman = _plugman(server)
    return {
        "available": True,
        "remote": True,
        "note": (f"Стоит {plugman}: изменения применяются сразу, без перезапуска." if plugman
                 else "Изменения начнут работать после перезапуска сервера."),
        "plugman": {"installed": bool(plugman), "name": plugman},
        "enabled": enabled,
        "disabled": [item(e, False) for e in _jars(server, "plugins/disabled")],
        "updates": [item(e, False) for e in _jars(server, "plugins/update")],
        "running": True,
    }


def _to_trash(server: GameServer, path: str, filename: str, name: str | None, version: str | None) -> None:
    """Moves a jar to the trash and remembers what it was, for «Версии» (core/plugin_history.py)."""
    from apps.api.app.core import plugin_history

    trash_name = f"{int(time.time())}-{filename}"
    remote_files.call(server, "rename", path=path, to=f"{TRASH}/{trash_name}")
    plugin_history.remember(server, trash_name, name=name or _guess_name(filename), version=version)


def _inventory_entry(server: GameServer, filename: str) -> dict:
    inv = integration_updates.inventory(server) or {}
    return next((p for p in inv.get("plugins") or [] if p.get("file") == filename), {})


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
        label = (f"{meta['name']} {old.get('version') or ''} → {meta['version']}" if old
                 else f"{meta['name']} {meta['version']} (новый)")
        log: list[str] = []
        loaded_old = _loaded_name(server, old["filename"]) if (old and was_on) else None
        # PlugMan cannot reload itself: a new PlugMan waits for the restart like any plugin
        hot = _plugman(server) if meta["name"].lower() not in ("plugmanx", "plugman") else None
        if hot and loaded_old:
            log.append(_console(server, f"plugman unload {loaded_old}"))
        if old and old["filename"] == base and was_on and not hot:
            # no PlugMan: Paper swaps a same-named jar in from plugins/update at start
            remote_files.call(server, "fetch", timeout=120.0, url=blob["url"], path=f"plugins/update/{base}", sha256=blob["sha256"])
        else:
            if old and (old["filename"] != base or not was_on or hot):
                where = "plugins" if was_on else "plugins/disabled"
                _to_trash(server, f"{where}/{old['filename']}", old["filename"], old.get("name"), old.get("version"))
            remote_files.call(server, "fetch", timeout=120.0, url=blob["url"], path=f"plugins/{base}", sha256=blob["sha256"])
        if hot:
            log.append(_console(server, f"plugman load {_stem(base)}"))
        result = "\n".join(log) if hot else AFTER_RESTART
        done.append({"filename": base, "status": "applied", "label": label, "result": result})
    return done


def change(server: GameServer, filename: str, op: str) -> dict:
    name = rfs.norm(filename)
    if "/" in name or not name.lower().endswith(".jar"):
        raise RemoteFileError("Некорректное имя файла", 400)
    if op not in ("disable", "enable", "remove"):
        raise RemoteFileError("Неизвестное действие", 400)
    hot = _plugman(server)
    loaded = _loaded_name(server, name) if op in ("disable", "remove") else None
    if hot and loaded and loaded.lower() in ("plugmanx", "plugman"):
        hot = None   # PlugMan does not unload itself: that one waits for the restart
    log: list[str] = []
    if hot and loaded:
        log.append(_console(server, f"plugman unload {loaded}"))
    if op == "disable":
        remote_files.call(server, "rename", path=f"plugins/{name}", to=f"plugins/disabled/{name}")
    elif op == "enable":
        remote_files.call(server, "rename", path=f"plugins/disabled/{name}", to=f"plugins/{name}")
        if hot:
            log.append(_console(server, f"plugman load {_stem(name)}"))
    else:
        src = f"plugins/{name}" if rfs.stat(server, f"plugins/{name}") else f"plugins/disabled/{name}"
        inv = _inventory_entry(server, name)
        _to_trash(server, src, name, inv.get("name"), inv.get("version"))
    return {"status": "applied", "result": "\n".join(log) if hot and log else AFTER_RESTART}


def rollback(server: GameServer, found: dict, cur: dict | None, installed: dict) -> dict:
    """Puts a version from the trash back (see core/plugin_history.py): the current one goes to
    the trash, the chosen one into its place — loaded at once through PlugMan when it runs."""
    from apps.api.app.core import plugin_history

    filename, trash_name = found["filename"], found["id"]
    enabled_files = {p["filename"] for p in installed["enabled"]}
    cur_on = bool(cur) and cur["filename"] in enabled_files
    if cur and cur["filename"] != filename and any(
            p["filename"] == filename for p in installed["enabled"] + installed["disabled"]):
        raise RemoteFileError(f"Файл {filename} уже занят другим плагином", 409)
    is_plugman = (found.get("name") or "").lower() in ("plugmanx", "plugman")
    hot = None if is_plugman else _plugman(server)
    log: list[str] = []
    if cur and cur_on and not hot and cur["filename"] == filename:
        # Same file name, no PlugMan: Paper swaps it in from plugins/update at start; the
        # running jar is not touched (it cannot be kept — the swap overwrites it).
        remote_files.call(server, "rename", path=f"{TRASH}/{trash_name}", to=f"plugins/update/{filename}")
        plugin_history.forget(server, trash_name)
        return {"status": "applied", "result": AFTER_RESTART}
    if cur:
        if hot and cur_on:
            loaded = _loaded_name(server, cur["filename"])
            if loaded:
                log.append(_console(server, f"plugman unload {loaded}"))
        _to_trash(server, f"{'plugins' if cur_on else 'plugins/disabled'}/{cur['filename']}", cur["filename"],
                  cur.get("name"), cur.get("version"))
    dest = "plugins" if (cur_on or not cur) else "plugins/disabled"
    remote_files.call(server, "rename", path=f"{TRASH}/{trash_name}", to=f"{dest}/{filename}")
    plugin_history.forget(server, trash_name)
    if hot and dest == "plugins":
        log.append(_console(server, f"plugman load {_stem(filename)}"))
    if dest == "plugins/disabled":
        return {"status": "applied", "result": "возвращён выключенным, как и был"}
    return {"status": "applied", "result": "\n".join(log) if hot else AFTER_RESTART}
