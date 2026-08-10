from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from apps.api.app.db import SessionLocal
from apps.bot.permissions import perms_for
from apps.bot.services.linking import user_by_telegram_id


class ContextMiddleware(BaseMiddleware):
    """Opens a DB session per update, resolves the linked user + permission set,
    and exposes them to handlers as ``session`` / ``user`` / ``perms``."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = SessionLocal()
        data["session"] = session
        tg_user = data.get("event_from_user")
        user = user_by_telegram_id(session, tg_user.id) if tg_user else None
        data["user"] = user
        data["perms"] = perms_for(user)
        try:
            result = await handler(event, data)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
