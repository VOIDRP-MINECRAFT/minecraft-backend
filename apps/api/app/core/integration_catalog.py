"""What an external server installs to join VoidRP — the «Интеграция» page.

Each entry says what the piece does, which modules it reports (core/server_reports.py), on
which server cores it runs, what it needs, and how to build its config for one server. Our
own builds are published as ``plugin_releases`` and downloaded from the panel; third-party
dependencies link to their official pages at the version we run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from apps.api.app.config import get_settings
from apps.api.app.models.game_server import GameServer

PLUGIN_CORES = ("paper", "folia")
MOD_CORES = ("neoforge", "hybrid")

CORE_LABELS = {
    "paper": "Paper",
    "folia": "Folia",
    "neoforge": "NeoForge",
    "hybrid": "Гибрид NeoForge + Paper (Youer, Mohist)",
}


def auth_method(server: GameServer) -> str | None:
    """"plugin" (VoidRpAuth) for Paper/Folia, "mod" (voidrp-auth-bridge) for modded cores."""
    core = (server.server_core or "").lower()
    if core in PLUGIN_CORES:
        return "plugin"
    if core in MOD_CORES:
        return "mod"
    return None


def _backend_url() -> str:
    return get_settings().public_api_url.rstrip("/")


def _header(server: GameServer, comment: str = "#") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"{comment} Сгенерировано в админке VoidRP для сервера «{server.name}» ({server.slug}), {stamp}.\n"
        f"{comment} Внутри секрет сервера: не выкладывайте файл в открытый доступ и никому не передавайте.\n"
    )


def _auth_config(server: GameServer) -> str:
    return _header(server) + f'''# Вход и регистрация через аккаунт VoidRP.
backend:
  url: "{_backend_url()}"
  secret: "{server.game_auth_secret}"
  server-slug: "{server.slug}"
  timeout-ms: 15000

site:
  base-url: "https://void-rp.ru"
  offer-path: "/offer"
  privacy-path: "/privacy"
  reset-password-path: "/forgot-password"

login:
  # Сколько секунд ждать ввода в окне, прежде чем отключить игрока.
  timeout-seconds: 180
  # Сколько минут после выхода не спрашивать пароль повторно при том же адресе.
  session-minutes: 30
  # Окно входа до попадания в мир (клиент 1.21.6+); старые клиенты — /login и /register.
  pre-join-dialog: true

launcher:
  # Мгновенный вход по пропуску лаунчера для этого ника и адреса — оставляйте включённым.
  ticket-by-nickname: true
  # Запасной путь: пропуск в адресе подключения <пропуск>.<домен>, нужен wildcard в DNS.
  ticket-from-hostname: true
  verified-prefix: "&b✔ &r"
  verified-tab-suffix: "&b ✔"
'''


def _perms_config(server: GameServer) -> str:
    return _header(server) + f'''# VoidRP Perms: мониторинг, права в игре (LuckPerms), чат, консоль и лог, бан предметов, наказания.
backend-url: "{_backend_url()}"
game-auth-secret: "{server.game_auth_secret}"
server-slug: "{server.slug}"
# Как часто забирать изменения из админки (сек) и отправлять список групп и прав (мин).
poll-seconds: 10
catalog-minutes: 5
blocked-message: "&cПрава настраиваются только в админке: &fvoid-rp.ru/admin &7(«Права в игре»)"
# Чат с префиксами групп LuckPerms. auto — только если нет своего чат-плагина.
chat:
  mode: auto
  format: "{{prefix}}{{name}}{{suffix}}&7: &f{{message}}"
# Консоль, лог и чат, бан предметов, баны и муты — всё из админки, без RCON и EssentialsX.
# auto — включено, если это не делает другой плагин VoidRP (бан предметов — VoidRpGameSync).
modules:
  console: auto
  log: auto
  item_bans: auto
  punishments: auto
'''


def _guard_config(server: GameServer) -> str:
    return _header(server) + f'''# VoidRP Guard: античит. Пороги, откаты и остальное — в админке, раздел «Античит».
backend:
  url: "{_backend_url()}"
  secret: "{server.game_auth_secret}"
  server-slug: "{server.slug}"
  timeout-ms: 10000
'''


def _bridge_config(server: GameServer) -> str:
    return _header(server) + f'''# voidrp-auth-bridge: вход через лаунчер VoidRP на сервере с модами.
backend={_backend_url()}
gameSecret={server.game_auth_secret}
timeoutMs=60000
graceSecs=120
'''


# key → description. ``required`` is for the server cores listed in ``cores``.
#
# ``repo`` — our GitHub repository: a tag ``v1.2.0`` there makes CI publish a GitHub Release,
# and ``apps.worker.release_sync`` takes it into ``plugin_releases`` (changelog = the tag's
# message). ``release`` says how to read a release: the platforms and Minecraft versions of a
# jar whose name has no ``+mc<ver>``, and per-version platforms for one that has.
CATALOG: list[dict[str, Any]] = [
    {
        "key": "voidrp-auth", "name": "VoidRpAuth", "kind": "ours", "cores": list(PLUGIN_CORES),
        "required": True, "modules": ["auth"],
        "summary": "Вход через аккаунт VoidRP: игроки из лаунчера заходят сразу по пропуску, остальные — окном с паролем. "
                   "Закрывает вход под чужим ником на сервере в offline-mode.",
        "install_as": "plugins/VoidRpAuth.jar", "config_path": "plugins/VoidRpAuth/config.yml",
        "needs": [],
        "repo": "voidrp-auth-plugin", "release": {"platforms": ["paper", "folia"], "mc": ["26.2"]},
    },
    {
        "key": "voidrp-auth-bridge", "name": "voidrp-auth-bridge", "kind": "ours", "cores": list(MOD_CORES),
        "required": True, "modules": ["auth"],
        "summary": "Вход через лаунчер VoidRP для серверов на модах: мод стоит на сервере и в клиентском паке игроков.",
        "install_as": "mods/voidrp_auth_bridge.jar", "config_path": "config/voidrp-auth-bridge.properties",
        "needs": [],
        "repo": "voidrp-auth-bridge",
        "release": {"platforms": ["neoforge", "hybrid"], "mc": ["1.21.1"], "by_mc": {"26.2": ["neoforge"]}},
    },
    {
        "key": "voidrp-perms", "name": "VoidRpPerms", "kind": "ours", "cores": list(PLUGIN_CORES),
        "required": True, "modules": ["monitoring", "perms", "chat", "console", "log", "item_bans", "punishments"],
        "summary": "Мониторинг для админки (TPS, игроки, память), права в игре из раздела «Права в игре», чат с префиксами, "
                   "консоль, лог и чат сервера в админке (RCON не нужен), бан предметов, баны и муты (EssentialsX не нужен).",
        "install_as": "plugins/VoidRpPerms.jar", "config_path": "plugins/VoidRpPerms/config.yml",
        "needs": ["luckperms"],
        "repo": "voidrp-perms", "release": {"platforms": ["paper", "folia"], "mc": ["1.21.1", "26.2"]},
    },
    {
        "key": "voidrp-guard", "name": "VoidRpGuard", "kind": "ours", "cores": ["paper"],
        "required": False, "modules": ["anticheat"],
        "summary": "Античит: флаги GrimAC, проверки клиентов, иксрей и гриф с откатами CoreProtect — всё в разделе «Античит».",
        "install_as": "plugins/VoidRpGuard.jar", "config_path": "plugins/VoidRpGuard/config.yml",
        "needs": ["grimac", "packetevents", "coreprotect"],
        "repo": "voidrp-guard", "release": {"platforms": ["paper"], "mc": ["26.2"]},
    },
    {
        "key": "voidrp-client-info", "name": "VoidRP Client Info", "kind": "ours", "cores": ["paper"],
        "required": False, "modules": [], "client_side": True,
        "summary": "Для клиентского пака на NeoForge: присылает серверу список модов игрока и проверку на инжекты, "
                   "VoidRpGuard передаёт их в «Античит». Ставится игрокам в пак (скрытым обязательным модом), не на сервер.",
        "install_as": "mods/voidrp_client_info.jar", "config_path": None,
        "needs": ["voidrp-guard"],
        "repo": "voidrp-client-info", "release": {"platforms": ["neoforge"], "mc": ["26.2"]},
    },
    # Third-party: official downloads at the version we run.
    {"key": "luckperms", "name": "LuckPerms", "kind": "third_party", "cores": list(PLUGIN_CORES),
     "version": "5.5.71", "url": "https://luckperms.net/download",
     "summary": "Хранит группы и права. Нужен для VoidRpPerms."},
    {"key": "grimac", "name": "GrimAC", "kind": "third_party", "cores": ["paper"],
     "version": "2.3.74", "url": "https://modrinth.com/plugin/grimac",
     "summary": "Античит движения и боя, его флаги собирает VoidRpGuard."},
    {"key": "packetevents", "name": "packetevents", "kind": "third_party", "cores": ["paper"],
     "version": "2.13.0", "url": "https://modrinth.com/plugin/packetevents",
     "summary": "Библиотека для GrimAC."},
    {"key": "coreprotect", "name": "CoreProtect CE", "kind": "third_party", "cores": ["paper"],
     "version": "24.1", "url": "https://modrinth.com/plugin/coreprotect",
     "summary": "Журнал блоков: откаты грифа из раздела «Античит»."},
]

CONFIG_BUILDERS: dict[str, Callable[[GameServer], str]] = {
    "voidrp-auth": _auth_config,
    "voidrp-perms": _perms_config,
    "voidrp-guard": _guard_config,
    "voidrp-auth-bridge": _bridge_config,
}


def entry(key: str) -> dict[str, Any] | None:
    return next((e for e in CATALOG if e["key"] == key), None)


def for_server(server: GameServer) -> list[dict[str, Any]]:
    """Catalog entries that apply to this server's core (all of them when it is unknown)."""
    core = (server.server_core or "").lower()
    return [e for e in CATALOG if not core or core in e["cores"]]


def releases_dir() -> str:
    return get_settings().releases_dir
