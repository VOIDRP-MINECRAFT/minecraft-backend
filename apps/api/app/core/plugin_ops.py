"""Plugins of a Paper-based server: what is installed (from each jar's plugin.yml or
paper-plugin.yml), what is switched off (plugins/disabled/), what waits in the queue,
and uploading new ones and new versions through a staging area."""
from __future__ import annotations

import os
import re
import shutil
import uuid
import zipfile

import yaml
from sqlalchemy.orm import Session

from apps.api.app.core import mod_ops, server_changes
from apps.api.app.models.game_server import GameServer

STAGING_BASE = os.path.join(mod_ops.OPS_BASE, "plugin-staging")


# A jar's meta never changes while the file stays the same: keyed by path + mtime + size,
# so the plugins page stops re-opening every jar (~0.05 s each) on every refresh.
_META_CACHE: dict[tuple[str, int, int], dict] = {}
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def read_meta(path: str) -> dict:
    """name, version, authors, dependencies — or {"error": …} for a jar that is no plugin."""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key and key in _META_CACHE:
        return dict(_META_CACHE[key])
    meta = _read_meta(path)
    if key:
        if len(_META_CACHE) > 2000:
            _META_CACHE.clear()
        _META_CACHE[key] = meta
    return dict(meta)


def _read_meta(path: str) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            source = "paper-plugin.yml" if "paper-plugin.yml" in names else ("plugin.yml" if "plugin.yml" in names else None)
            if source is None:
                return {"error": "В jar нет plugin.yml — это не плагин Paper/Bukkit (мод? библиотека?)"}
            data = yaml.load(zf.read(source).decode("utf-8", "replace"), Loader=_YAML_LOADER) or {}
    except (zipfile.BadZipFile, OSError, yaml.YAMLError) as exc:
        return {"error": f"Не читается как плагин: {exc}"}
    authors = data.get("authors") or ([data["author"]] if data.get("author") else [])
    depend = data.get("depend") or []
    softdepend = data.get("softdepend") or []
    if isinstance(data.get("dependencies"), dict):  # paper-plugin.yml
        server_deps = (data["dependencies"].get("server") or {})
        depend = [n for n, d in server_deps.items() if (d or {}).get("required", True)]
        softdepend = [n for n, d in server_deps.items() if not (d or {}).get("required", True)]
    return {
        "name": str(data.get("name") or ""),
        "version": str(data.get("version") or ""),
        "authors": [str(a) for a in authors][:5],
        "description": str(data.get("description") or "")[:300],
        "depend": [str(d) for d in depend],
        "softdepend": [str(d) for d in softdepend],
        "paper": source == "paper-plugin.yml",
        "api_version": str(data.get("api-version") or ""),
    }


def _scan(directory: str) -> list[dict]:
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory), key=str.lower):
        path = os.path.join(directory, name)
        if name.lower().endswith(".jar") and os.path.isfile(path):
            out.append({"filename": name, "size": os.path.getsize(path), **read_meta(path)})
    return out


def list_plugins(session: Session, server: GameServer) -> dict:
    try:
        base = server_changes.folder(server, "plugin")
    except server_changes.ChangeError:
        return {"available": False, "enabled": [], "disabled": [], "updates": []}
    if not os.path.isdir(base):
        return {"available": False, "enabled": [], "disabled": [], "updates": []}
    enabled = _scan(base)
    for p in enabled:
        p["config_folder"] = f"plugins/{p['name']}" if p.get("name") and os.path.isdir(os.path.join(base, p["name"])) else None
    plugman = next((p for p in enabled if (p.get("name") or "").lower() in ("plugmanx", "plugman")), None)
    return {
        "available": True,
        # PlugMan(X) lets plugin changes be applied without restarting the server.
        "plugman": {"installed": plugman is not None, "name": plugman.get("name") if plugman else None},
        "enabled": enabled,
        "disabled": _scan(os.path.join(base, "disabled")),
        "updates": _scan(os.path.join(base, "update")),
        "running": server_changes.running(server),
    }


def _staging(slug: str, token: str | None = None) -> str:
    if token is not None and not re.fullmatch(r"[0-9a-f]{16}", token):
        raise mod_ops.ModOpsError("Некорректный токен загрузки")
    return os.path.join(STAGING_BASE, slug, token or "")


def stage(session: Session, server: GameServer, files: list[tuple[str, bytes]]) -> dict:
    """Keeps uploaded jars aside and says what each would do: a new plugin, a new version
    of one installed (which it would replace), or no plugin at all; and which required
    plugins are missing."""
    if not files:
        raise mod_ops.ModOpsError("Не выбрано ни одного файла")
    token = uuid.uuid4().hex[:16]
    d = _staging(server.slug, token)
    os.makedirs(d, exist_ok=True)
    installed = list_plugins(session, server)
    by_name = {p["name"].lower(): p for p in installed["enabled"] + installed["disabled"] if p.get("name")}
    entries = []
    for fname, data in files:
        base = mod_ops.sanitize_jar(fname)
        path = os.path.join(d, base)
        mod_ops._atomic_write(path, data)
        entries.append({"filename": base, "size": len(data), **read_meta(path)})
    staged_names = {e["name"].lower() for e in entries if e.get("name")}
    have = set(by_name) | staged_names
    for e in entries:
        if e.get("error"):
            continue
        old = by_name.get(e["name"].lower())
        if old:
            e["replaces"] = old["filename"]
            e["replaces_version"] = old.get("version")
            e["same_version"] = old.get("version") == e.get("version")
        e["missing_depend"] = [dep for dep in e["depend"] if dep.lower() not in have]
    return {"token": token, "files": entries}


def apply_staged(session: Session, server: GameServer, token: str, filenames: list[str], created_by: str | None) -> dict:
    d = _staging(server.slug, token)
    if not os.path.isdir(d):
        raise mod_ops.ModOpsError("Загрузка не найдена или устарела — загрузите заново")
    installed = list_plugins(session, server)
    by_name = {p["name"].lower(): p for p in installed["enabled"] + installed["disabled"] if p.get("name")}
    queued = []
    for fname in filenames:
        base = mod_ops.sanitize_jar(fname)
        src = os.path.join(d, base)
        if not os.path.isfile(src):
            raise mod_ops.ModOpsError(f"Файл не найден в загрузке: {base}")
        meta = read_meta(src)
        if meta.get("error"):
            raise mod_ops.ModOpsError(f"{base}: {meta['error']}")
        old = by_name.get(meta["name"].lower())
        label = f"{meta['name']} {old.get('version')} → {meta['version']}" if old else f"{meta['name']} {meta['version']} (новый)"
        change = server_changes.queue(
            session, server, kind="plugin", op="add", filename=old["filename"] if old and old["filename"] == base else base,
            source_path=server_changes.keep_source(server, src, base), replaces=old["filename"] if old else None,
            label=label, created_by=created_by,
        )
        queued.append({"filename": base, "status": change.status, "label": label, "result": change.result})
    shutil.rmtree(d, ignore_errors=True)
    return {"queued": queued}


# ── Applying plugin changes without a restart (PlugMan) ──────────────────────

def _rcon(server: GameServer, command: str) -> str:
    from apps.api.app.core import server_ops

    return server_ops.strip_color_codes(server_ops.rcon_command(server, command, timeout=30) or "").strip()


def _dependents(enabled: list[dict], name: str) -> list[dict]:
    """Loaded plugins that need ``name`` (directly or through another), outermost first."""
    out: list[dict] = []
    frontier = {name.lower()}
    while True:
        more = [p for p in enabled if p not in out and p.get("name") and
                frontier & {d.lower() for d in p.get("depend", []) + p.get("softdepend", [])}]
        if not more:
            return list(reversed(out))
        out.extend(more)
        frontier = {p["name"].lower() for p in more}


def apply_hot(session: Session, server: GameServer) -> list[dict]:
    """The queued plugin changes, applied on the running server through PlugMan: the
    plugin (and whatever depends on it) is unloaded, its jar swapped, and loaded again.
    Each step's answer is kept in the change's result. Mods are not touched — they need
    a restart whatever happens."""
    from apps.api.app.models.server_change import ServerFileChange

    info = list_plugins(session, server)
    if not info.get("plugman", {}).get("installed"):
        raise mod_ops.ModOpsError("На сервере нет PlugMan — примените изменения перезапуском")
    enabled = info["enabled"]
    by_file = {p["filename"]: p for p in enabled + info["disabled"]}
    results = []
    changes = [c for c in server_changes.pending(session, server) if c.kind == "plugin"]
    base = server_changes.folder(server, "plugin")
    for change in changes:
        log: list[str] = []
        try:
            if change.op == "add":
                meta = read_meta(change.source_path or "")
            else:
                meta = by_file.get(change.filename) or by_file.get(change.replaces or "") or {}
            name = meta.get("name")
            if not name:
                raise mod_ops.ModOpsError("Не удалось понять название плагина")
            loaded_name = (by_file.get(change.replaces or change.filename) or {}).get("name") if change.op in ("add", "remove", "disable") else None
            deps = _dependents(enabled, name) if loaded_name else []
            for d in deps:
                log.append(f"unload {d['name']}: {_rcon(server, f'plugman unload {d['name']}')}")
            if loaded_name and (change.op != "add" or change.replaces):
                log.append(f"unload {loaded_name}: {_rcon(server, f'plugman unload {loaded_name}')}")
            server_changes.apply_one(session, server, change)  # the file operation, now nothing holds the jar
            if change.status == "failed":
                raise mod_ops.ModOpsError(change.result or "файл не применён")
            if change.op in ("add", "enable"):
                stem = change.filename[:-4]
                log.append(f"load {stem}: {_rcon(server, f'plugman load {stem}')}")
            for d in reversed(deps):
                stem = d["filename"][:-4]
                if os.path.isfile(os.path.join(base, d["filename"])):
                    log.append(f"load {stem}: {_rcon(server, f'plugman load {stem}')}")
            bad = [line for line in log if any(w in line.lower() for w in ("error", "failed", "could not", "not found", "exception"))]
            change.result = (change.result or "") + " · PlugMan: " + " | ".join(log)
            if bad:
                change.result += " · ⚠ проверьте консоль — возможно, нужен перезапуск"
            session.commit()
            results.append({"filename": change.filename, "status": change.status, "result": change.result, "warning": bool(bad)})
        except Exception as exc:  # noqa: BLE001 — one plugin's trouble is reported, the rest go on
            if change.status == "pending":
                change.result = f"Не применено через PlugMan: {exc}. " + " | ".join(log)
            else:
                change.result = (change.result or "") + f" · PlugMan: {exc} · " + " | ".join(log)
            session.commit()
            results.append({"filename": change.filename, "status": change.status, "result": change.result, "warning": True})
    return results
