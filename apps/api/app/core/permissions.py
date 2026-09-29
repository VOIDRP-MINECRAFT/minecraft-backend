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
            {"key": "servers.manage", "label": "Серверы (создание/редактирование)", "sensitive": True},
            {"key": "servers.hidden.view", "label": "Скрытые серверы: видеть на сайте и в лаунчере", "sensitive": True},
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
        "group": "Voxel Engine",
        "permissions": [
            {"key": "voxel.view", "label": "Voxel Engine: игры (просмотр)"},
            {"key": "voxel.manage", "label": "Voxel Engine: создавать/править игры", "sensitive": True},
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
    "salary.", "backups.", "punishments.", "battlepass.", "voxel.", "upgrader.",
    "trader.", "news.", "files.", "plugins.",
)

for _group in PERMISSION_CATALOG:
    for _p in _group["permissions"]:
        _p["scope"] = "server" if _p["key"].startswith(SERVER_SCOPED_PREFIXES) else "global"

SERVER_KEYS: frozenset[str] = frozenset(
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"] if p["scope"] == "server"
)

# Grants sight of ``game_servers.staff_only`` servers in the public catalogue
# (/servers) that feeds the site and the launcher. Full admins bypass it.
HIDDEN_SERVERS_PERMISSION = "servers.hidden.view"

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


def resolve_user_permissions(user, server_id=None) -> set[str]:
    """Effective permission set for a User object on one server.

    Full admins get every key. A moderator gets their platform-wide grants
    (``staff_permissions`` — global keys, and per-server keys granted on every
    server) plus, when ``server_id`` is given, the per-server keys granted on that
    server (``staff_server_permissions``). Everyone else gets nothing. Shared by
    the admin API (``caller_permissions``) and the Telegram bot.
    """
    if user is None or not getattr(user, "is_active", True):
        return set()
    if getattr(user, "is_admin", False):
        return set(ALL_KEYS)
    if getattr(user, "is_moderator", False):
        keys = set(sanitize_permissions(user.staff_permissions or []))
        if server_id is not None:
            per = (getattr(user, "staff_server_permissions", None) or {}).get(str(server_id)) or []
            keys |= {k for k in sanitize_permissions(per) if k in SERVER_KEYS}
        return keys
    return set()


def servers_with_permission(user, key: str, all_server_ids) -> set[str]:
    """The servers (ids as strings) on which the user holds ``key``."""
    ids = {str(i) for i in all_server_ids}
    if user is None or not getattr(user, "is_active", True):
        return set()
    if getattr(user, "is_admin", False) or key in (user.staff_permissions or []):
        return ids
    per = getattr(user, "staff_server_permissions", None) or {}
    return {sid for sid, keys in per.items() if key in (keys or []) and sid in ids}


_ORDERED_KEYS: list[str] = [
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]
]
