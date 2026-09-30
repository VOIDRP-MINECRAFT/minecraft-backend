"""Item names and icons for admin pickers, read from the deployed site.

The site already ships ``item_names.json`` (id → name, built from the pack's lang files) and
``item-icons/<namespace>/<item>.png``. Those name every translation key, not only items, so
a search should run over a server's own item registry when its plugin has reported one
(``server_items.item_ids``); without it, over every name that looks like an item id.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from apps.api.app.config import get_settings

ITEM_ID_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")

_lock = threading.Lock()
_names: dict[str, str] = {}
_names_mtime: float | None = None
_icons: set[str] = set()
_icons_at = 0.0
_ICONS_TTL = 600.0


def normalize_item_id(raw: str) -> str | None:
    """``Reliquary:Rod_Of_Lyssa `` → ``reliquary:rod_of_lyssa``; a bare name gets ``minecraft:``."""
    value = (raw or "").strip().lower()
    if value and ":" not in value:
        value = f"minecraft:{value}"
    return value if ITEM_ID_RE.match(value) and len(value) <= 128 else None


def _public() -> Path:
    return Path(get_settings().site_public_dir)


def _load() -> None:
    global _names, _names_mtime, _icons, _icons_at
    path = _public() / "item_names.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if mtime != _names_mtime:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _names = {k.lower(): v for k, v in raw.items() if isinstance(v, str)}
        except (OSError, ValueError):
            _names = {}
        _names_mtime = mtime
    if time.monotonic() - _icons_at > _ICONS_TTL:
        icons: set[str] = set()
        base = _public() / "item-icons"
        try:
            for ns in os.scandir(base):
                if ns.is_dir():
                    for f in os.scandir(ns.path):
                        if f.name.endswith(".png"):
                            icons.add(f"{ns.name}:{f.name[:-4]}".lower())
        except OSError:
            pass
        _icons, _icons_at = icons, time.monotonic()


def _name_of(item_id: str) -> str:
    return _names.get(item_id) or item_id.split(":", 1)[-1].replace("_", " ").replace("/", " ").capitalize()


def describe(item_ids) -> dict[str, dict]:
    """``{id: {"name", "icon"}}`` for items shown in a list."""
    with _lock:
        _load()
        return {i: {"name": _name_of(i), "icon": i in _icons} for i in item_ids}


def search(query: str, registry: list[str] | None, limit: int = 60) -> list[dict]:
    """Items matching ``query`` by id or name, best first.

    ``registry`` — the server's own item ids; ``None`` means the server has not reported
    them, so every name that looks like an item is searched (and marked unverified).
    """
    q = (query or "").strip().lower()
    words = [w for w in q.split() if w]
    with _lock:
        _load()
        pool = registry if registry is not None else [k for k in _names if ITEM_ID_RE.match(k)]
        scored: list[tuple[tuple, str]] = []
        for item_id in pool:
            name = _name_of(item_id)
            hay = f"{item_id} {name.lower()}"
            if words and not all(w in hay for w in words):
                continue
            path = item_id.split(":", 1)[-1]
            rank = (
                0 if q and (item_id == q or path == q or name.lower() == q) else
                1 if q and (name.lower().startswith(q) or path.startswith(q)) else 2,
                0 if item_id in _icons else 1,
                len(item_id),
                item_id,
            )
            scored.append((rank, item_id))
        scored.sort()
        return [
            {"id": i, "name": _name_of(i), "icon": i in _icons, "verified": registry is not None}
            for _, i in scored[:limit]
        ]
