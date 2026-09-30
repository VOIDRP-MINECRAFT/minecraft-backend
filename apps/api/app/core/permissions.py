"""Moderator permission catalog — single source of truth for staff RBAC.

Full admins (``users.is_admin``) bypass all checks. Moderators
(``users.is_moderator``) are granted a subset of these keys in
``users.staff_permissions``. The frontend fetches this catalog to render the
permission toggles when assigning a moderator.
"""
from __future__ import annotations

# key -> human label. ``sensitive`` keys are grantable but off in the preset.
PERMISSION_CATALOG: list[dict] = [
    {
        "group": "Обзор",
        "permissions": [
            {"key": "dashboard.view", "label": "Дашборд (общая сводка)"},
            {"key": "metrika.view", "label": "Метрика (Яндекс: визиты, отказы)", "sensitive": True},
            {"key": "donate.view", "label": "Донаты (платежи, выручка)", "sensitive": True},
            {"key": "battlepass.view", "label": "Battle Pass (просмотр)", "sensitive": True},
            {"key": "battlepass.manage", "label": "Battle Pass: выдавать/снимать премиум", "sensitive": True},
            {"key": "battlepass.rewards.manage", "label": "Battle Pass: править награды и сезоны", "sensitive": True},
        ],
    },
    {
        "group": "Сервер",
        "permissions": [
            {"key": "monitoring.view", "label": "Мониторинг (CPU/RAM/лог/TPS)"},
            {"key": "monitoring.restart", "label": "Питание сервера: запуск/перезапуск/остановка", "sensitive": True},
            {"key": "monitoring.rcon", "label": "RCON-консоль (команды)", "sensitive": True},
            {"key": "mods.view", "label": "Моды (просмотр списка)"},
            {"key": "mods.manage", "label": "Моды: добавлять/удалять/заменять, пересборка", "sensitive": True},
            {"key": "plugins.view", "label": "Плагины (список, версии, очередь изменений)"},
            {"key": "plugins.manage", "label": "Плагины: загружать/обновлять/выключать/удалять, применять с перезапуском", "sensitive": True},
            {"key": "players.online.view", "label": "Онлайн игроки (просмотр)"},
            {"key": "players.online.moderate", "label": "Онлайн: кик/бан/оп", "sensitive": True},
            {"key": "market.view", "label": "Рынок (просмотр)", "sensitive": True},
            {"key": "market.manage", "label": "Рынок: менять цены/товары", "sensitive": True},
            {"key": "nations.view", "label": "Государства (просмотр)"},
            {"key": "nations.manage", "label": "Государства (изменение)", "sensitive": True},
            {"key": "anticheat.view", "label": "Античит (просмотр)", "sensitive": True},
            {"key": "anticheat.manage", "label": "Античит: действия/вердикты/конфиг", "sensitive": True},
            {"key": "salary.view", "label": "Зарплата за игру (выплаты, настройки)"},
            {"key": "salary.manage", "label": "Зарплата за игру: менять суммы и лимиты", "sensitive": True},
        ],
    },
    {
        "group": "Бэкапы",
        "permissions": [
            {"key": "backups.view", "label": "Бэкапы (список, расписание)"},
            {"key": "backups.create", "label": "Бэкапы: создавать вручную", "sensitive": True},
            {"key": "backups.restore", "label": "Бэкапы: откатывать мир (перезапуск сервера)", "sensitive": True},
            {"key": "backups.delete", "label": "Бэкапы: удалять", "sensitive": True},
            {"key": "backups.settings", "label": "Бэкапы: менять расписание", "sensitive": True},
        ],
    },
    {
        "group": "Файлы сервера",
        "permissions": [
            {"key": "files.view", "label": "Файлы: смотреть папку сервера и читать конфиги", "sensitive": True},
            {"key": "files.edit", "label": "Файлы: править текстовые файлы (с историей и откатом)", "sensitive": True},
            {"key": "files.upload", "label": "Файлы: загружать, создавать папки, переименовывать", "sensitive": True},
            {"key": "files.delete", "label": "Файлы: удалять", "sensitive": True},
            {"key": "files.secrets", "label": "Файлы: видеть пароли и секреты в конфигах", "sensitive": True},
        ],
    },
    {
        "group": "Платформа",
        "permissions": [
            {"key": "players.view", "label": "Игроки (поиск, просмотр)", "sensitive": True},
            {"key": "players.manage", "label": "Игроки: правки (legacy-вход и т.п.)", "sensitive": True},
            {"key": "servers.manage", "label": "Серверы: настройки сервера (создавать и удалять — только с галочкой на всех)", "sensitive": True},
            {"key": "servers.hidden.view", "label": "Скрытые серверы: видеть на сайте и в лаунчере", "sensitive": True},
            {"key": "servers.maintenance.join", "label": "Вход на сервер во время тех. работ", "sensitive": True},
        ],
    },
    {
        "group": "Сотрудники",
        "permissions": [
            {"key": "staff.manage", "label": "Сотрудники: вкладка и личные права (выдавать можно только те, что есть у тебя)", "sensitive": True},
            {"key": "staff.sessions", "label": "Сотрудники: видеть их входы и завершать их (только тем, кто ниже)", "sensitive": True},
            {"key": "staff.mfa.reset", "label": "Сотрудники: сбрасывать 2FA, если потерян телефон (только тем, кто ниже, после пароля)", "sensitive": True},
            {"key": "roles.manage", "label": "Роли: создавать и править роли этого сервера (ниже своей, только с правами, что есть у тебя)", "sensitive": True},
            {"key": "roles.assign", "label": "Роли: выдавать и снимать роли этого сервера (ниже своей)", "sensitive": True},
            {"key": "badges.manage", "label": "Значки: создавать и править (роли без прав)"},
            {"key": "badges.assign", "label": "Значки: выдавать и снимать — себе тоже"},
        ],
    },
    {
        "group": "Права в игре (LuckPerms)",
        "permissions": [
            {"key": "game.view", "label": "Права в игре: смотреть группы и кто в них"},
            {"key": "game.assign", "label": "Права в игре: выдавать группы людям и класть их в роли (легче своей группы)", "sensitive": True},
            {"key": "game.groups.manage", "label": "Права в игре: менять состав групп (не входит в админство — выдаёт владелец)", "sensitive": True},
        ],
    },
    {
        "group": "Безопасность",
        "permissions": [
            {"key": "punishments.view", "label": "Наказания (список банов/мутов)"},
            {"key": "punishments.manage", "label": "Наказания: выдавать/снимать баны и муты", "sensitive": True},
            {"key": "audit.view", "label": "Журнал действий персонала", "sensitive": True},
        ],
    },
    {
        "group": "Обратная связь",
        "permissions": [
            {"key": "mod_suggestions.view", "label": "Предложения модов (просмотр)"},
            {"key": "mod_suggestions.manage", "label": "Предложения модов (изменять/удалять)", "sensitive": True},
            {"key": "feedback.view", "label": "Обращения (просмотр)"},
            {"key": "feedback.manage", "label": "Обращения (изменять/удалять)", "sensitive": True},
            {"key": "crashes.view", "label": "Краши лаунчера (просмотр)"},
            {"key": "crashes.manage", "label": "Краши лаунчера (удалять)"},
            {"key": "crashes.rules.manage", "label": "Правила крашей лаунчера (изменять — кнопки правил трогают файлы игроков)", "sensitive": True},
        ],
    },
    {
        "group": "Сайт",
        "permissions": [
            {"key": "landing.manage", "label": "Главная страница (лендинг)", "sensitive": True},
            {"key": "news.updates.view", "label": "Обновления (просмотр)"},
            {"key": "news.updates.manage", "label": "Обновления (публикация/редактирование)"},
            {"key": "news.media.view", "label": "Новости/медиа (просмотр)"},
            {"key": "news.media.manage", "label": "Новости/медиа (публикация/редактирование)"},
        ],
    },
    {
        "group": "Лаунчер",
        "permissions": [
            {"key": "launcher.view", "label": "Лаунчер: статус релиза (версия, манифест)"},
            {"key": "launcher.deploy", "label": "Лаунчер: менять версию, собирать и деплоить", "sensitive": True},
        ],
    },
    {
        "group": "Telegram",
        "permissions": [
            {"key": "telegram.games.manage", "label": "TG-бот: управление игровыми чатами", "sensitive": True},
        ],
    },
    {
        "group": "Апгрейдер",
        "permissions": [
            {"key": "upgrader.view", "label": "Апгрейдер: пул наград (просмотр)"},
            {"key": "upgrader.manage", "label": "Апгрейдер: править награды/настройки", "sensitive": True},
        ],
    },
    {
        "group": "Скупщик",
        "permissions": [
            {"key": "trader.view", "label": "Скупщик: визиты, каталог и сделки (просмотр)"},
            {"key": "trader.manage", "label": "Скупщик: править каталог/настройки, вызывать и завершать визиты", "sensitive": True},
        ],
    },
    {
        "group": "Косметика (Figura)",
        "permissions": [
            {"key": "figura.wardrobe", "label": "Figura: открывать меню мода (гардероб/загрузка)", "sensitive": True},
            {"key": "figura.cosmetics.manage", "label": "Figura: загружать модели и выдавать косметику", "sensitive": True},
        ],
    },
]

# Which permissions are given per server (a moderator can have the market on Origins
# and nothing on the main server) and which are one for the whole platform (news of the
# site as a whole, the launcher, accounts). Checked against the server a request is about
# — ``?server=``, ``?server_id=`` or ``X-Server-Slug``, else the default server; decided
# from which routes each key guards (the 2026-09-29 audit).
SERVER_SCOPED_PREFIXES: tuple[str, ...] = (
    "monitoring.", "mods.", "players.online.", "market.", "nations.", "anticheat.",
    "salary.", "backups.", "punishments.", "battlepass.", "upgrader.",
    "trader.", "news.", "files.", "plugins.", "donate.", "audit.", "feedback.", "mod_suggestions.",
    "badges.", "game.",
)
# Per-server keys outside those prefixes. Crash reports carry the server picked in the
# launcher; the crash *rules* stay platform-wide, their buttons touch players' files.
SERVER_SCOPED_KEYS: frozenset[str] = frozenset({"crashes.view", "crashes.manage", "servers.manage", "dashboard.view",
                                               "roles.manage", "roles.assign", "servers.maintenance.join"})

for _group in PERMISSION_CATALOG:
    for _p in _group["permissions"]:
        _p["scope"] = "server" if _p["key"].startswith(SERVER_SCOPED_PREFIXES) or _p["key"] in SERVER_SCOPED_KEYS else "global"

SERVER_KEYS: frozenset[str] = frozenset(
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"] if p["scope"] == "server"
)

# Per-server keys an admin of a server does NOT get just by being its admin — they are
# given separately (by a role or personally) when really needed.
NOT_VIA_SERVER_ADMIN: frozenset[str] = frozenset({"servers.manage", "game.groups.manage"})
SERVER_ADMIN_KEYS: frozenset[str] = SERVER_KEYS - NOT_VIA_SERVER_ADMIN

for _group in PERMISSION_CATALOG:
    for _p in _group["permissions"]:
        _p["via_admin"] = _p["key"] in SERVER_ADMIN_KEYS

# Grants sight of ``game_servers.staff_only`` servers in the public catalogue
# (/servers) that feeds the site and the launcher. Full admins bypass it.
HIDDEN_SERVERS_PERMISSION = "servers.hidden.view"
MAINTENANCE_JOIN_PERMISSION = "servers.maintenance.join"


def may_join_during_maintenance(user, server) -> bool:
    """Whether the user may play on ``server`` while it is under maintenance: platform
    admins, and holders of ``servers.maintenance.join`` on it (admins of the server have it)."""
    if user is None:
        return False
    return MAINTENANCE_JOIN_PERMISSION in access_of(user).on(server.id)

ALL_KEYS: frozenset[str] = frozenset(
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]
)

# Default "Стандартный модератор" preset — pre-checked when assigning a moderator.
MODERATOR_PRESET: list[str] = [
    "dashboard.view",
    "monitoring.view",
    "players.online.view",
    "nations.view",
    "mod_suggestions.view",
    "feedback.view",
    "crashes.view",
    "crashes.manage",
    "news.updates.view",
    "news.updates.manage",
    "news.media.view",
    "news.media.manage",
]


def sanitize_permissions(keys: list[str] | None) -> list[str]:
    """Keep only known keys, de-duplicated, in catalog order."""
    given = set(keys or [])
    return [k for k in _ORDERED_KEYS if k in given]


def sanitize_server_permissions(grants: dict | None) -> dict[str, list[str]]:
    """``{server_id: [keys]}`` keeping only per-server keys, dropping empty servers."""
    out: dict[str, list[str]] = {}
    for server_id, keys in (grants or {}).items():
        kept = [k for k in sanitize_permissions(keys) if k in SERVER_KEYS]
        if kept:
            out[str(server_id)] = kept
    return out


class Access:
    """Everything a person may do in the admin panel, from every source.

    Sources, most senior first: the owner / platform admins (``is_admin``, every key
    everywhere); admins of single servers (``admin_server_ids``, every per-server key
    there); roles (``staff_roles`` — keys on every server, or per-server keys on the
    role's servers); personal grants (``staff_permissions`` everywhere,
    ``staff_server_permissions`` per server). ``everywhere`` holds keys valid on every
    server (and the platform keys); ``per_server`` the extra keys of single servers.
    """

    def __init__(self, user) -> None:
        self.user = user
        active = user is not None and getattr(user, "is_active", True)
        self.platform_admin = bool(active and getattr(user, "is_admin", False))
        self.admin_servers: set[str] = set()
        self.everywhere: set[str] = set()
        self.per_server: dict[str, set[str]] = {}
        if not active or self.platform_admin:
            return
        self.admin_servers = {str(i) for i in (getattr(user, "admin_server_ids", None) or [])}
        if not (getattr(user, "is_moderator", False) or self.admin_servers):
            return
        self.everywhere |= set(sanitize_permissions(user.staff_permissions or []))
        for sid, keys in (getattr(user, "staff_server_permissions", None) or {}).items():
            self._add(str(sid), keys)
        for role in getattr(user, "staff_roles", None) or []:
            if getattr(role, "is_badge", False):
                continue
            if role.server_ids is None:
                self.everywhere |= set(sanitize_permissions(role.permissions or []))
            else:
                for sid in role.server_ids:
                    self._add(str(sid), role.permissions or [])

    def _add(self, sid: str, keys) -> None:
        kept = {k for k in sanitize_permissions(keys) if k in SERVER_KEYS}
        if kept:
            self.per_server.setdefault(sid, set()).update(kept)

    @property
    def is_staff(self) -> bool:
        return self.platform_admin or bool(self.admin_servers or self.everywhere or self.per_server)

    def on(self, server_id=None) -> set[str]:
        """Effective keys on one server (None: only what holds everywhere)."""
        if self.platform_admin:
            return set(ALL_KEYS)
        keys = set(self.everywhere)
        if server_id is not None:
            sid = str(server_id)
            if sid in self.admin_servers:
                keys |= SERVER_ADMIN_KEYS
            keys |= self.per_server.get(sid, set())
        return keys

    def holds_everywhere(self, key: str) -> bool:
        return self.platform_admin or key in self.everywhere

    def servers_with(self, key: str, all_server_ids) -> set[str]:
        ids = {str(i) for i in all_server_ids}
        if self.holds_everywhere(key):
            return ids
        out = {sid for sid, keys in self.per_server.items() if key in keys}
        if key in SERVER_ADMIN_KEYS:
            out |= self.admin_servers
        return out & ids

    def is_admin_of(self, server_id) -> bool:
        return self.platform_admin or str(server_id) in self.admin_servers


def access_of(user) -> Access:
    return Access(user)


def resolve_user_permissions(user, server_id=None) -> set[str]:
    """Effective permission set for a User object on one server (see Access). Shared by
    the admin API (``caller_permissions``) and the Telegram bot."""
    return Access(user).on(server_id)


def servers_with_permission(user, key: str, all_server_ids) -> set[str]:
    """The servers (ids as strings) on which the user holds ``key``."""
    return Access(user).servers_with(key, all_server_ids)


_ORDERED_KEYS: list[str] = [
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]
]
