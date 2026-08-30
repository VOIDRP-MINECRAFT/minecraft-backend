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
            {"key": "players.online.view", "label": "Онлайн игроки (просмотр)"},
            {"key": "players.online.moderate", "label": "Онлайн: кик/бан/оп", "sensitive": True},
            {"key": "market.view", "label": "Рынок (просмотр)", "sensitive": True},
            {"key": "market.manage", "label": "Рынок: менять цены/товары", "sensitive": True},
            {"key": "nations.view", "label": "Государства (просмотр)"},
            {"key": "nations.manage", "label": "Государства (изменение)", "sensitive": True},
            {"key": "anticheat.view", "label": "Античит (просмотр)", "sensitive": True},
            {"key": "anticheat.manage", "label": "Античит: действия/вердикты/конфиг", "sensitive": True},
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
]

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


def resolve_user_permissions(user) -> set[str]:
    """Effective permission set for a User object.

    Full admins get every key; moderators get their sanitized granted subset;
    everyone else gets nothing. Shared by the admin API (``caller_permissions``)
    and the Telegram bot so both agree on what a user can do.
    """
    if user is None or not getattr(user, "is_active", True):
        return set()
    if getattr(user, "is_admin", False):
        return set(ALL_KEYS)
    if getattr(user, "is_moderator", False):
        return set(sanitize_permissions(user.staff_permissions or []))
    return set()


_ORDERED_KEYS: list[str] = [
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]
]
