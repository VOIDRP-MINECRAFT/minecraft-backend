"""What a server runs (VoidRpPerms' inventory), what clashes with VoidRP, and the updates
VoidRpPerms may take by itself when the owner turned them on.

The inventory arrives with the heartbeat every ten minutes and is kept a day in Redis: the
page lists the plugins, missing dependencies and known conflicts from it. With
``integration_settings.auto_update`` on, the heartbeat's answer carries the newer builds that
suit the server — ours by the version it reports, third-party dependencies only up to the
version we tested — and VoidRpPerms puts them in the update folder for the next start.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings

from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import integration_state
from apps.api.app.core.releases import version_key
from apps.api.app.models.game_server import GameServer
from apps.api.app.services.redis_cache_service import RedisCacheService

INVENTORY_TTL = 24 * 3600

# Plugins that get in VoidRP's way, with what to do.
CONFLICTS: dict[str, str] = {
    "authme": "AuthMe спорит с VoidRpAuth за вход игроков — уберите его.",
    "authmereloaded": "AuthMe спорит с VoidRpAuth за вход игроков — уберите его.",
    "nlogin": "nLogin спорит с VoidRpAuth за вход игроков — уберите его.",
    "librelogin": "LibreLogin спорит с VoidRpAuth за вход игроков — уберите его.",
    "jpremium": "JPremium спорит с VoidRpAuth за вход игроков — уберите его.",
    "fastlogin": "FastLogin переключает игроков в online-mode, а аккаунты VoidRP без лицензии — уберите его.",
    "skinsrestorer": "SkinsRestorer не нужен: VoidRpAuth 1.4+ сам ставит скин из аккаунта VoidRP. Пока он включён, скины VoidRP не работают.",
    "luckpermschat": "Чат с префиксами уже делает VoidRpPerms — второй форматирует строки дважды.",
}


def store_inventory(server: GameServer, inventory: dict[str, Any]) -> None:
    plugins = [
        {"name": str(p.get("name"))[:64], "version": str(p.get("version") or "")[:48],
         "enabled": bool(p.get("enabled", True)), "file": str(p.get("file") or "")[:160]}
        for p in (inventory.get("plugins") or [])[:300] if isinstance(p, dict) and p.get("name")
    ]
    props = {str(k)[:40]: str(v)[:40] for k, v in (inventory.get("server_properties") or {}).items()}
    from apps.api.app.core.security import utc_now

    configs = {}
    for name, c in list((inventory.get("configs") or {}).items())[:20]:
        if isinstance(c, dict):
            configs[str(name)[:64]] = {"keys": [str(k)[:120] for k in (c.get("keys") or [])[:300]],
                                       "backend_url": str(c.get("backend_url") or "")[:200] or None}
    RedisCacheService().set_json(f"integration_inventory:{server.id}", {
        "plugins": plugins, "java": str(inventory.get("java") or "")[:32], "server_properties": props,
        "configs": configs, "at": utc_now().isoformat(),
    }, ttl_seconds=INVENTORY_TTL)


def inventory(server: GameServer) -> dict[str, Any] | None:
    return RedisCacheService().get_json(f"integration_inventory:{server.id}")


def analysis(server: GameServer, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Conflicts, missing dependencies and server.properties issues from the inventory."""
    inv = inventory(server)
    if not inv:
        return None
    have = {p["name"].lower(): p for p in inv["plugins"]}
    issues: list[dict[str, str]] = []
    for name, why in CONFLICTS.items():
        if name in have and have[name]["enabled"]:
            issues.append({"level": "err", "text": f"{have[name]['name']} {have[name]['version']}: {why}"})
    by_key = {i["key"]: i for i in items}
    for it in items:
        if it["kind"] != "ours" or not it.get("installed"):
            continue
        for dep in it.get("needs") or []:
            d = by_key.get(dep)
            dep_name = (d or {}).get("plugin_name") or (d or {}).get("name") or dep
            if d and d.get("kind") == "third_party" and dep_name.lower() not in have:
                issues.append({"level": "warn", "text": f"{it['name']} нужен {dep_name} — его нет на сервере ({d.get('url')})."})
    for it in items:
        if it["kind"] != "third_party":
            continue
        p = have.get((it.get("plugin_name") or it["name"]).lower())
        if p and it.get("version") and version_key(_plain(p["version"])) < version_key(it["version"]):
            issues.append({"level": "info", "text": f"{p['name']} {p['version']} старее проверенной нами {it['version']}."})
    issues += _config_issues(server, items, inv.get("configs") or {})
    props = inv.get("server_properties") or {}
    if props.get("online-mode") == "true":
        issues.append({"level": "err", "text": "online-mode=true: игроки VoidRP без лицензии не зайдут. Нужен online-mode=false (вход проверяет VoidRpAuth)."})
    # Our own servers are run over RCON on purpose; a partner's needs it closed.
    if server.is_external and props.get("enable-rcon") == "true" and any(r.get("modules", {}).get("console", {}).get("ok")
                                                   for r in [i.get("installed") or {} for i in items]):
        issues.append({"level": "warn", "text": f"RCON включён (порт {props.get('rcon.port', '25575')}), хотя консоль идёт через VoidRpPerms — выключите enable-rcon."})
    return {"at": inv["at"], "java": inv["java"], "plugins": inv["plugins"], "issues": issues}


def _leaf_keys(data: Any, prefix: str = "") -> set[str]:
    if not isinstance(data, dict):
        return {prefix} if prefix else set()
    out: set[str] = set()
    for k, v in data.items():
        out |= _leaf_keys(v, f"{prefix}.{k}" if prefix else str(k))
    return out


def _config_issues(server: GameServer, items: list[dict[str, Any]], configs: dict[str, Any]) -> list[dict[str, str]]:
    """Settings the current template has but a plugin's config.yml lacks, and a backend address
    other than ours — from the key names VoidRpPerms 0.6.2+ reports (never the values)."""
    import yaml
    from urllib.parse import urlparse

    out: list[dict[str, str]] = []
    ours_host = urlparse(get_settings().public_api_url).hostname
    for it in items:
        if it["kind"] != "ours" or it["key"] not in cat.CONFIG_BUILDERS or not (it.get("config_path") or "").endswith(".yml"):
            continue
        reported = configs.get(it.get("plugin_name") or it["name"])
        if not reported:
            continue
        try:
            template = _leaf_keys(yaml.safe_load(cat.CONFIG_BUILDERS[it["key"]](server)))
        except yaml.YAMLError:
            continue
        missing = sorted(template - set(reported["keys"]))
        if missing:
            shown = ", ".join(missing[:6]) + (f" и ещё {len(missing) - 6}" if len(missing) > 6 else "")
            out.append({"level": "info", "text": f"В конфиге {it['name']} нет настроек из новой версии: {shown}. "
                        "Работают значения по умолчанию; чтобы видеть и менять их — возьмите свежий конфиг во вкладке «Плагины»."})
        url = reported.get("backend_url")
        if url and urlparse(url).hostname not in (ours_host, "127.0.0.1", "localhost"):
            out.append({"level": "warn", "text": f"{it['name']} обращается к {url}, а адрес VoidRP — {get_settings().public_api_url}."})
    return out


def _plain(v: str) -> str:
    """'v5.5.71-bukkit' → '5.5.71': the comparable part of a third-party version."""
    v = v.strip().lstrip("vV")
    out = []
    for ch in v:
        if ch.isdigit() or ch == ".":
            out.append(ch)
        else:
            break
    return "".join(out) or v


def updates_for(session: Session, server: GameServer) -> dict[str, Any]:
    """The heartbeat's answer for VoidRpPerms: whether auto-update is on, and what to take."""
    settings = server.integration_settings or {}
    if not settings.get("auto_update"):
        return {"auto_update": False}
    from apps.api.app.core import integration_scripts

    items = integration_state.plugin_items(session, server)
    out = []
    for it in items:
        if it["kind"] == "ours" and it.get("outdated") and it.get("latest"):
            latest = it["latest"]
            if latest["channel"] == "beta" and not settings.get("beta"):
                continue
            out.append({"name": it.get("plugin_name") or it["name"], "version": latest["version"],
                        # A path, not a URL: the plugin puts it after its own backend-url, so the
                        # secret goes exactly where the plugin already talks to.
                        "hash": f"sha256:{latest['sha256']}", "url": f"/game-sync/integration/file/{latest['id']}"})
    inv = inventory(server) or {}
    have = {p["name"].lower(): p for p in inv.get("plugins", [])}
    for it in items:
        if it["kind"] != "third_party" or not it.get("modrinth") or not it.get("version"):
            continue
        p = have.get((it.get("plugin_name") or it["name"]).lower())
        if not p or version_key(_plain(p["version"])) >= version_key(it["version"]):
            continue
        f = integration_scripts.modrinth_file(it["modrinth"], it["version"], server.mc_version)
        if f and f.get("sha512") and it["version"] in f.get("version", ""):
            out.append({"name": p["name"], "version": f["version"], "hash": f"sha512:{f['sha512']}", "url": f["url"]})
    return {"auto_update": True, "updates": out}


def mark_old_secret(server: GameServer, plugin: str) -> None:
    """A plugin of this server still talks with the secret before the rotation."""
    cache = RedisCacheService()
    key = f"integration_old_secret:{server.id}"
    seen = cache.get_json(key) or {}
    from apps.api.app.core.security import utc_now

    seen[plugin[:64]] = utc_now().isoformat()
    cache.set_json(key, seen, ttl_seconds=26 * 3600)


def old_secret_plugins(server: GameServer) -> list[str]:
    """Plugins that used the previous secret within the last two minutes."""
    from datetime import datetime, timedelta

    from apps.api.app.core.security import utc_now

    seen = RedisCacheService().get_json(f"integration_old_secret:{server.id}") or {}
    now = utc_now()
    return sorted(p for p, at in seen.items() if now - datetime.fromisoformat(at) < timedelta(minutes=2))
