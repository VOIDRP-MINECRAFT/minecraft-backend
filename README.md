# ⚙️ VoidRP Backend

> Центральный REST API сервера VoidRP — авторизация, нации, экономика, античит, донат.

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Alembic](https://img.shields.io/badge/Alembic-migrations-lightgrey)
![License](https://img.shields.io/badge/license-proprietary-red)

---

## 🗺️ Место в экосистеме

```
  Лаунчер (Electron / JavaFX)
        │ play-ticket auth (HTTPS)
        ▼
┌──────────────────────────────┐
│   minecraft-backend  ◄───────┼── Сайт (Vue 3)  [JWT]
│   FastAPI · PostgreSQL       │
│   void-rp.ru / api/v1        │
└───────────┬──────────────────┘
            │ X-Game-Auth-Secret (HTTP)
            ▼
  Minecraft Server (Mohist 1.21.1)
  └── gamesync-plugin · anticheat · cpm-companion
```

---

## ✨ Возможности

- **Авторизация** — регистрация, JWT access + opaque refresh токены, legacy Minecraft auth
- **Play-ticket flow** — одноразовые тикеты для входа в игру (лаунчер → backend → сервер)
- **Нации и альянсы** — создание, членство, казна, статистика, дипломатия, голосования
- **Динамическая экономика** — рыночные цены предметов, история сделок
- **Battle Pass** — сезонная система, Premium-статус, синхронизация с плагином
- **Ежедневные квесты** — пул заданий, прогресс, интеграция с плагином
- **Античит** — приём отчётов о нарушениях, снимков модов, детектов инъекций
- **Admin Panel API** — управление игроками, вердикты по модам, действия
- **Рефералы и донат** — интеграция с платёжной системой
- **Медиа** — аватары, скины, статические файлы через `/media`

---

## 🔐 Три уровня авторизации

| Слой | Заголовок | Используется |
|---|---|---|
| Пользователь | `Authorization: Bearer <JWT>` | Сайт, лаунчер |
| Администратор | `X-Admin-Api-Secret` | Admin panel |
| Игровой сервер | `X-Game-Auth-Secret` | Плагины, моды |

---

## 📋 Требования

| Компонент | Версия |
|---|---|
| Python | 3.12+ |
| PostgreSQL | 15+ |
| Redis | опционально |

---

## 🚀 Быстрый старт

```bash
cd minecraft_backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # заполни DATABASE_URL, JWT_SECRET_KEY и др.

alembic upgrade head          # применить все миграции
uvicorn apps.api.app.main:app --reload
```

**Swagger UI:** `http://127.0.0.1:8000/docs`

### Полезные команды

```bash
# Создать новую миграцию после изменения модели
alembic revision --autogenerate -m "описание"

# Тесты
pytest

# Lint / format
ruff check . && ruff format .
```

---

## 🏗️ Структура

```
apps/api/app/
├── main.py                  # точка входа, create_app()
├── config.py                # Settings (pydantic-settings, .env)
├── api/routes/              # маршруты по доменам
│   ├── auth.py              # /auth/register, /auth/login, /auth/refresh
│   ├── me.py                # /me/profile, /me/skin
│   ├── nations.py           # /nations/*
│   ├── alliances.py         # /alliances/*
│   ├── market.py            # /market/items
│   ├── battlepass.py        # /battlepass/*
│   ├── daily_quests.py      # /daily-quests/*
│   ├── game_sync_*.py       # /server/* (X-Game-Auth-Secret)
│   └── admin_*.py           # /admin/* (X-Admin-Api-Secret)
├── models/                  # SQLAlchemy 2.0 ORM модели
├── schemas/                 # Pydantic v2 схемы запрос/ответ
├── repositories/            # слой доступа к данным
├── dependencies/            # FastAPI DI: auth.py, admin.py, server_auth.py
└── core/
    ├── security.py          # JWT, Argon2 хэширование
    └── user_messages.py     # локализация ошибок EN → RU
```

---

## 🔗 Связанные репозитории

| Репо | Связь |
|---|---|
| [voidrp-site](https://github.com/VOIDRP-MINECRAFT/voidrp-site) | Сайт — основной потребитель API |
| [voidrp-launcher-vue](https://github.com/VOIDRP-MINECRAFT/voidrp-launcher-vue) | Лаунчер — play-ticket auth |
| [voidrp-gamesync-plugin](https://github.com/VOIDRP-MINECRAFT/voidrp-gamesync-plugin) | Плагин — синхронизация через X-Game-Auth-Secret |
| [voidrp-anticheat](https://github.com/VOIDRP-MINECRAFT/voidrp-anticheat) | Античит мод — отправляет отчёты в `/anticheat/*` |

---

<div align="center">
<a href="https://void-rp.ru">🌐 Сайт</a> ·
<a href="https://github.com/VOIDRP-MINECRAFT">🏠 Организация</a>
</div>
