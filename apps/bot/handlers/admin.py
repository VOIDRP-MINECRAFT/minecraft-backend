from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.orm import Session

from apps.api.app.models.user import User
from apps.bot.keyboards import gamechat_kb
from apps.bot.permissions import can_manage_games
from apps.bot.services import games as g

router = Router(name="admin")


def _thread(message: Message) -> int | None:
    return message.message_thread_id if getattr(message, "is_topic_message", False) else None


# ── Commands just post a confirm button. The actual permission check happens on
#    the button press, whose callback carries the REAL user even when the group
#    admin posts anonymously (as GroupAnonymousBot / on behalf of the chat). ──
@router.message(Command("allowgames"))
async def cmd_allowgames(message: Message) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эту команду используй в нужном игровом чате/топике.")
        return
    await message.answer(
        "🎮 Включить мини-игры в этом чате/топике? Нажми кнопку (проверю твои права).",
        reply_markup=gamechat_kb("on", _thread(message)),
    )


@router.message(Command("disallowgames"))
async def cmd_disallowgames(message: Message) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эту команду используй в нужном игровом чате/топике.")
        return
    await message.answer(
        "Выключить мини-игры в этом чате/топике?",
        reply_markup=gamechat_kb("off", _thread(message)),
    )


@router.message(Command("gamechats"))
async def cmd_gamechats(message: Message) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Нажми кнопку, чтобы показать список (проверю права):", reply_markup=gamechat_kb("list", None))
        return
    await message.answer("Показать список игровых чатов?", reply_markup=gamechat_kb("list", _thread(message)))


@router.callback_query(F.data.startswith("gc:"))
async def on_gamechat_action(cb: CallbackQuery, user: User | None, perms: set[str], session: Session) -> None:
    if user is None:
        await cb.answer("Сначала привяжи аккаунт в ЛС бота: /start", show_alert=True)
        return
    if not can_manage_games(perms):
        await cb.answer("У тебя нет прав на управление играми.", show_alert=True)
        return

    _, action, raw_thread = cb.data.split(":")
    thread = int(raw_thread) or None
    chat_id = cb.message.chat.id

    if action == "on":
        added = g.allow_game_chat(session, chat_id, thread, cb.message.chat.title, user.id)
        where = f" (топик {thread})" if thread else ""
        await cb.message.edit_text(
            f"✅ Игры включены в этом чате{where}. Пишите /games." if added
            else f"ℹ️ Игры уже были включены здесь{where}."
        )
    elif action == "off":
        removed = g.disallow_game_chat(session, chat_id, thread)
        await cb.message.edit_text("🚫 Игры выключены здесь." if removed else "ℹ️ Игры тут и так не были включены.")
    elif action == "list":
        rows = g.list_game_chats(session)
        if not rows:
            await cb.message.edit_text("Пока нет игровых чатов. Зайди в нужный чат/топик и напиши /allowgames.")
        else:
            lines = ["🎮 <b>Игровые чаты</b>\n"]
            for r in rows:
                title = r.title or str(r.chat_id)
                topic = f" · топик {r.thread_id}" if r.thread_id else ""
                lines.append(f"• {title}{topic}")
            await cb.message.edit_text("\n".join(lines))
    await cb.answer()
