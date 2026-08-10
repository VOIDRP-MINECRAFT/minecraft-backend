from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from apps.api.app.config import get_settings
from apps.bot.handlers import admin, games, news, start
from apps.bot.middlewares import ContextMiddleware

logger = logging.getLogger("voidrp.bot")

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Старт / привязка аккаунта"),
    BotCommand(command="whoami", description="Кто я и мои права"),
    BotCommand(command="help", description="Справка"),
]

GROUP_COMMANDS = [
    BotCommand(command="games", description="Список игр"),
    BotCommand(command="dice", description="🎲 Бросок кубика"),
    BotCommand(command="slots", description="🎰 Слот-машина"),
    BotCommand(command="guess", description="🔢 Угадай число"),
    BotCommand(command="quiz", description="🧠 Викторина"),
    BotCommand(command="duel", description="⚔️ Дуэль (ответом на игрока)"),
    BotCommand(command="rps", description="✊ Камень-ножницы-бумага"),
    BotCommand(command="daily", description="🎁 Ежедневная награда"),
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
