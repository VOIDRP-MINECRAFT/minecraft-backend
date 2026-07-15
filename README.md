# ⚙️ VoidRP Backend

> Центральный REST API сервера VoidRP — авторизация, нации, экономика, античит, донат, WebGUI game-ui.

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
┌──────────────────────────────────────────┐
│   minecraft-backend  ◄───────────────────┼── Сайт (Vue 3)  [JWT]
│   FastAPI · PostgreSQL                   │
│   api.void-rp.ru / api/v1                │
└───────────┬──────────────────────────────┘
            │                    ▲
            │ X-Game-Auth-Secret │ webgui_token (HMAC-SHA256)
            ▼                    │
  Minecraft Server (Mohist)  Minecraft Client (MCEF browser)
  └── gamesync-plugin         └── void-rp.ru/game-ui/*
      anticheat
      cpm-companion
```

---

## ✨ Возможности

- **Авторизация** — регистрация, JWT access + opaque refresh токены, legacy Minecraft auth
- **Play-ticket flow** — одноразовые тикеты для входа в игру (лаунчер → backend → сервер)
- **Нации и альянсы** — создание, членство, казна, статистика, дипломатия, голосования
- **Динамическая экономика** — рыночные цены предметов, история сделок
- **Рынок игроков** — ордера, доставки, pending web actions (для WebGUI)
- **Battle Pass** — сезонная система, Premium-статус, синхронизация с плагином
- **Ежедневные квесты** — пул заданий, прогресс, интеграция с плагином
- **Античит** — приём отчётов о нарушениях, снимков модов, детектов инъекций
- **Admin Panel API** — управление игроками, вердикты по модам, действия
- **WebGUI Game-UI** — API для браузерных страниц внутри Minecraft клиента
- **Медиа** — аватары, скины, статические файлы через `/media`
- **Мульти-сервер** — общий аккаунт, но игровые данные скоупятся по серверу (см. ниже)

---

## 🖥️ Мульти-сервер

Платформа поддерживает несколько игровых серверов при **едином аккаунте**.
`users` / `player_accounts` — глобальные, а все игровые данные (нации, альянсы,
экономика, статистика, play-tickets, battlepass, античит…) скоупятся по
`server_id` → `game_servers`.

- **`game_servers`** (`models/game_server.py`): `slug`, витрина, подключение
  (`host`/`port`/`mc_version`/`loader`/`neoforge_version`), модпак
  (`pack_root`/`manifest_url`/…), доступ (`whitelist_mode`, `maintenance`),
  `features` (JSONB — какие вкладки показывать) и уникальный `game_auth_secret`.
  Ровно один сервер `is_default=True`.
- **Резолв сервера:**
  - плагины/game-sync → `dependencies/server_auth.py` по `X-Game-Auth-Secret`
    (у каждого сервера свой секрет; legacy-секрет → дефолтный сервер);
  - сайт/лаунчер → `dependencies/server_context.py` по `?server=<slug>` →
    заголовку `X-Server-Slug` → дефолтному серверу.
- **Admin:** `routes/admin_servers.py` (`/admin/servers`, CRUD + regenerate-secret
  + загрузка иконок). **Public:** `routes/servers.py` (`/servers`, live-пинг через
  mcstatus с кэшем 30 с).
- **Миграции:** `20260706_0001` (таблица + дефолт-сид) и `20260706_0002`
  (`server_id` в 30 таблиц + свопы уникальных индексов).

---

## 🔐 Четыре уровня авторизации

| Слой | Заголовок / Параметр | Используется |
|---|---|---|
| Пользователь | `Authorization: Bearer <JWT>` | Сайт, лаунчер |
| Администратор | `X-Admin-Api-Secret` | Admin panel |
| Игровой сервер | `X-Game-Auth-Secret` | Плагины, моды |
| WebGUI | `?webgui_token=<HMAC-SHA256>` | MCEF-браузер в игре |

### WebGUI токен

HMAC-SHA256 токен, подписываемый Paper-плагином (`WebGuiBridgeService.signUrl()`):
```
payload = base64url("1|<playerNickname>|<expiresAtEpoch>")
token   = payload + "." + base64url(HMAC-SHA256(payload, secret))
```

Секрет задаётся в `.env` как `WEBGUI_TOKEN_SECRET_BASE64` (тот же ключ, что в `config/webgui/server.json` мода).

Верификация в `dependencies/webgui_auth.py`:
```python
def get_webgui_player(webgui_token: str = Query(...), ...) -> PlayerAccount:
    # HMAC verify → check expiry → lookup by minecraft_nickname_normalized
```

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
alembic revision --autogenerate -m "описание"   # новая миграция
pytest                                           # тесты
ruff check . && ruff format .                    # lint + format
```

---

## 🏗️ Структура

```
apps/api/app/
├── main.py                  точка входа, create_app()
├── config.py                Settings (pydantic-settings, .env)
├── api/routes/
│   ├── auth.py              /auth/register, /auth/login, /auth/refresh
│   ├── me.py                /me/profile, /me/skin
│   ├── nations.py           /nations/*
│   ├── alliances.py         /alliances/*
│   ├── market.py            /market/items
│   ├── battlepass.py        /battlepass/*
│   ├── daily_quests.py      /daily-quests/*
│   ├── game_sync_*.py       /server/* (X-Game-Auth-Secret)
│   ├── game_ui_market.py    /game-ui/market/* (webgui_token)  ← WebGUI
│   └── admin_*.py           /admin/* (X-Admin-Api-Secret)
├── models/
│   ├── ...                  SQLAlchemy 2.0 ORM модели
│   └── player_market_web_action.py  ← pending actions от браузера
├── schemas/                 Pydantic v2 схемы запрос/ответ
├── repositories/            слой доступа к данным
├── dependencies/
│   ├── auth.py              JWT bearer
│   ├── admin.py             X-Admin-Api-Secret
│   ├── server_auth.py       X-Game-Auth-Secret
│   └── webgui_auth.py       webgui_token HMAC-SHA256  ← WebGUI
└── core/
    ├── security.py          JWT, Argon2 хэширование
    └── user_messages.py     локализация ошибок EN → RU
```

---

## 🌐 WebGUI Game-UI роутер

Роутер `game_ui_market.py` обслуживает MCEF-браузер внутри Minecraft. Все эндпоинты принимают `?webgui_token=` вместо JWT.

### Эндпоинты `/api/v1/game-ui/market/`

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `order-book/{item_key}` | Книга ордеров по товару |
| `GET` | `my-orders` | Мои активные ордера |
| `GET` | `items` | Список товаров |
| `GET` | `trades` | История сделок |
| `POST` | `pending-action` | Создать действие для плагина (buy, cancel, pickup) |
| `GET` | `pickup-ready` | Количество незабранных доставок |

### PlayerMarketWebAction

Таблица `player_market_web_actions` — очередь действий от браузера к плагину:

```python
class PlayerMarketWebAction(Base):
    id: int
    player_nickname: str
    action_type: str        # "buy" | "cancel_sell" | "cancel_buy" | "pickup"
    payload_json: str       # JSON с параметрами
    status: str             # "pending" | "processing" | "done" | "failed"
    expires_at: datetime    # TTL 3-5 минут
    created_at: datetime
```

Плагин (`WebActionPollService`) поллит `GET /game-sync/market-web-actions` каждую секунду и подтверждает через `/ack`.

### `.env` переменные для WebGUI

```env
WEBGUI_TOKEN_SECRET_BASE64=<base64-encoded-32-bytes>
```

Должен совпадать с `tokenSecretBase64` в `config/webgui/server.json` NeoForge мода.

---

## 🔗 Связанные репозитории

| Репо | Связь |
|---|---|
| [voidrp-site](https://github.com/VOIDRP-MINECRAFT/voidrp-site) | Сайт — основной потребитель JWT API |
| [voidrp-gamesync-plugin](https://github.com/VOIDRP-MINECRAFT/voidrp-gamesync-plugin) | Плагин — X-Game-Auth-Secret + pending web actions |
| [voidrp-webgui-neoforge](https://github.com/VOIDRP-MINECRAFT/voidrp-webgui-neoforge) | NeoForge мод — генерирует webgui_token |
| [voidrp-anticheat](https://github.com/VOIDRP-MINECRAFT/voidrp-anticheat) | Мод — шлёт violation/mod-snapshot/injection-report |

---

<div align="center">
<a href="https://void-rp.ru">🌐 Сайт</a> ·
<a href="https://github.com/VOIDRP-MINECRAFT">🏠 Организация</a> ·
<a href="https://github.com/VOIDRP-MINECRAFT/.github/blob/main/docs/WEBGUI_ARCHITECTURE.md">📐 WebGUI Architecture</a>
</div>
