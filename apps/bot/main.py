from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.orm import configure_mappers
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

import apps.api.app.models  # noqa: F401  — register full ORM graph before any query
from apps.api.app.config import get_settings
from apps.bot.handlers import admin, games, news, start
from apps.bot.middlewares import ContextMiddleware

configure_mappers()

logger = logging.getLogger("voidrp.bot")

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Старт / привязка аккаунта"),
    BotCommand(command="whoami", description="Кто я и мои права"),
    BotCommand(command="help", description="Справка"),
]

GROUP_COMMANDS = [
    BotCommand(command="games", description="Список игр и правила"),
    BotCommand(command="dice", description="🎲 Кубик на ставку: /dice 20"),
    BotCommand(command="slots", description="🎰 Слоты на ставку: /slots 20"),
    BotCommand(command="duel", description="⚔️ Дуэль с игроком (ответом): /duel 50"),
    BotCommand(command="rps", description="✊ КНБ с игроком (ответом): /rps 30"),
    BotCommand(command="guess", description="🔢 Угадай число"),
    BotCommand(command="8ball", description="🎱 Магический шар"),
    BotCommand(command="daily", description="🎁 Ежедневная награда"),
    BotCommand(command="rescue", description="🆘 +5 войдов, если баланс 0"),
    BotCommand(command="top", description="🏆 Топ игроков"),
    BotCommand(command="me", description="💰 Мой счёт"),
]


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    ctx = ContextMiddleware()
    dp.message.middleware(ctx)
    dp.callback_query.middleware(ctx)
    # Command routers first; the broad news "prepared message" catcher goes last.
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(games.router)
    dp.include_router(news.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    proxy = settings.outbound_proxy_url or None
    session = AiohttpSession(proxy=proxy) if proxy else None
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    await _set_commands(bot)
    me = await bot.get_me()
    logger.info("Starting VoidRP bot @%s (proxy=%s)", me.username, bool(proxy))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
