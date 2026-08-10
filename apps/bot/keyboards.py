from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def link_kb(url: str) -> InlineKeyboardMarkup:
    from apps.bot.texts import LINK_BUTTON
    kb = InlineKeyboardBuilder()
    kb.button(text=LINK_BUTTON, url=url)
    return kb.as_markup()


def servers_kb(servers: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in servers:
        kb.button(text=s.name, callback_data=f"news:srv:{s.id}")
    kb.button(text="✖ Отмена", callback_data="news:cancel")
    kb.adjust(1)
    return kb.as_markup()


def category_kb(allowed: list[str]) -> InlineKeyboardMarkup:
    labels = {"update": "🛠 Обновления", "media": "📰 Новости"}
    kb = InlineKeyboardBuilder()
    for cat in allowed:
        kb.button(text=labels[cat], callback_data=f"news:cat:{cat}")
    kb.button(text="✖ Отмена", callback_data="news:cancel")
    kb.adjust(1)
    return kb.as_markup()


def targets_kb(targets: dict[str, bool]) -> InlineKeyboardMarkup:
    def mark(on: bool) -> str:
        return "✅" if on else "☐"
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{mark(targets['site'])} Сайт", callback_data="news:tgt:site")
    kb.button(text=f"{mark(targets['telegram'])} Telegram", callback_data="news:tgt:telegram")
    kb.button(text=f"{mark(targets['discord'])} Discord", callback_data="news:tgt:discord")
    kb.button(text="🚀 Опубликовать", callback_data="news:go")
    kb.button(text="✖ Отмена", callback_data="news:cancel")
    kb.adjust(1)
    return kb.as_markup()


def gamechat_kb(action: str, thread: int | None) -> InlineKeyboardMarkup:
    """Confirm button for game-chat management. The callback (button press)
    always carries the real user — even for anonymous group admins — so the
    permission check works where a plain message can't identify the sender."""
    labels = {"on": "✅ Включить игры здесь", "off": "🚫 Выключить игры здесь", "list": "📋 Показать список"}
    kb = InlineKeyboardBuilder()
    kb.button(text=labels[action], callback_data=f"gc:{action}:{thread or 0}")
    return kb.as_markup()


def rps_kb(stake: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🪨 Камень", callback_data=f"rps:rock:{stake}")
    kb.button(text="✂️ Ножницы", callback_data=f"rps:scissors:{stake}")
    kb.button(text="📄 Бумага", callback_data=f"rps:paper:{stake}")
    kb.adjust(3)
    return kb.as_markup()


def quiz_kb(options: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, opt in enumerate(options):
        kb.button(text=opt, callback_data=f"quiz:{i}")
    kb.adjust(1)
    return kb.as_markup()


def duel_kb(challenger_id: int, opponent_id: int, reward: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ Принять", callback_data=f"duel:accept:{challenger_id}:{opponent_id}:{reward}")
    kb.button(text="🏳 Отказаться", callback_data=f"duel:decline:{challenger_id}:{opponent_id}:{reward}")
    kb.adjust(2)
    return kb.as_markup()
