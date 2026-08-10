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
            {"key": "monitoring.restart", "label": "Перезапуск сервера (если неактивен)"},
            {"key": "monitoring.rcon", "label": "RCON-консоль (команды)", "sensitive": True},
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
]

ALL_KEYS: frozenset[str] = frozenset(
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]
)

# Default "Стандартный модератор" preset — pre-checked when assigning a moderator.
MODERATOR_PRESET: list[str] = [
    "dashboard.view",
    "monitoring.view",
    "monitoring.restart",
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


_ORDERED_KEYS: list[str] = [
    p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]
]
