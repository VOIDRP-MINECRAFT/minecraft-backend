# VoidRP Backend

FastAPI бэкенд для игрового проекта VoidRP — единая аккаунтная платформа, игровая статистика, донат-интеграция и API для лаунчера.

## Стек

- **Python 3.12** · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2
- **PostgreSQL** — основная БД
- **Redis** — опционально (для будущего кэширования)
- **Argon2** (pwdlib) — хэширование паролей
- **JWT** — access token; opaque refresh token хранится в БД

## Быстрый старт

```bash
cd minecraft_backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env           # заполни DATABASE_URL, JWT_SECRET_KEY и т.д.
alembic upgrade head
uvicorn apps.api.app.main:app --reload
```

Swagger UI: http://127.0.0.1:8000/docs

## Структура

```
apps/api/app/
├── api/routes/        # маршруты по доменам (auth, me, nations, battlepass, …)
├── models/            # SQLAlchemy ORM модели
├── schemas/           # Pydantic схемы запросов/ответов
├── dependencies/      # FastAPI DI: auth.py, admin.py, server_auth.py
├── repositories/      # слой доступа к данным
├── services/          # бизнес-логика (battlepass, easydonate, rcon, …)
├── core/              # security, user_messages, rcon_client
└── config.py          # Settings (pydantic-settings, .env)
```

## Слои авторизации

| Слой | Заголовок | Использование |
|---|---|---|
| Пользователь | `Authorization: Bearer <JWT>` | Все пользовательские маршруты |
| Админ | `X-Admin-Api-Secret` | `/api/v1/admin/*` |
| Игровой сервер | `X-Game-Auth-Secret` | `/api/v1/game-sync/*`, `/api/v1/nation-stats/*` |

## Основные домены

- **auth** — регистрация, логин, refresh, logout, верификация email, сброс пароля
- **me / account** — профиль, смена пароля, привязка ника
- **nations / alliances** — государства, альянсы, статистика, активность
- **battlepass** — Premium подписки, прогресс, RCON-интеграция
- **market** — внутриигровой рынок (EconomyMarketItem, транзакции)
- **admin** — дашборд, донат-отчётность, управление игроками
- **game-sync** — синхронизация данных от Paper-плагина

## Команды

```bash
# Миграции
alembic upgrade head
alembic revision --autogenerate -m "описание"

# Тесты
pytest
pytest tests/test_auth_flow.py::test_name

# Линтер / форматирование
ruff check .
ruff format .
```

## Переменные окружения (ключевые)

| Переменная | Описание |
|---|---|
| `DATABASE_URL` | PostgreSQL DSN |
| `JWT_SECRET_KEY` | секрет для подписи JWT |
| `ADMIN_API_SECRET` | секрет для X-Admin-Api-Secret |
| `GAME_AUTH_SHARED_SECRET` | секрет для X-Game-Auth-Secret |
| `RCON_HOST / RCON_PORT / RCON_PASSWORD` | RCON к Minecraft серверу |
| `EASYDONATE_SHOP_KEY` | ключ магазина EasyDonate |
| `YANDEX_METRIKA_TOKEN / COUNTER_ID` | Яндекс.Метрика |
| `EMAIL_BACKEND` | `logging` (дев) или `resend` (прод) |
| `MINECRAFT_SERVER_HOST / PORT` | для опроса статуса через mcstatus |
