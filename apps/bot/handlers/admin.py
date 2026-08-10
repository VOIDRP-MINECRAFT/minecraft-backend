from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.orm import Session

from apps.api.app.models.user import User
from apps.bot import texts
from apps.bot.permissions import can_manage_games
from apps.bot.services import games as g

router = Router(name="admin")

# Telegram's built-in bot that "sends" messages from anonymous group admins.
GROUP_ANONYMOUS_BOT_ID = 1087968824


def _thread(message: Message) -> int | None:
    return message.message_thread_id if getattr(message, "is_topic_message", False) else None


def _is_anonymous(message: Message) -> bool:
    """True when the message is posted on behalf of a chat (anonymous admin /
    channel), so we can't map it to a personal VoidRP account."""
    if message.sender_chat is not None:
        return True
    u = message.from_user
    return u is None or u.id == GROUP_ANONYMOUS_BOT_ID


async def _deny_if_no_access(message: Message, user: User | None, perms: set[str]) -> bool:
    """Returns True (and replies) if the caller may NOT manage games."""
    if _is_anonymous(message):
        await message.answer(texts.ANON_ADMIN)
        return True
    if user is None:
        await message.answer(texts.NOT_LINKED_SHORT)
        return True
    if not can_manage_games(perms):
        await message.answer(texts.NO_GAMES_PERM)
        return True
    return False


@router.message(Command("allowgames"))
async def cmd_allowgames(message: Message, user: User | None, perms: set[str], session: Session) -> None:
    if await _deny_if_no_access(message, user, perms):
        return
    thread = _thread(message)
    added = g.allow_game_chat(session, message.chat.id, thread, message.chat.title, user.id)
    where = f" (топик {thread})" if thread else ""
    await message.answer(
        f"✅ Игры включены в этом чате{where}." if added else f"ℹ️ Игры уже были включены здесь{where}."
    )


@router.message(Command("disallowgames"))
async def cmd_disallowgames(message: Message, user: User | None, perms: set[str], session: Session) -> None:
    if await _deny_if_no_access(message, user, perms):
        return
    removed = g.disallow_game_chat(session, message.chat.id, _thread(message))
    await message.answer("🚫 Игры выключены здесь." if removed else "ℹ️ Игры тут и так не были включены.")


@router.message(Command("gamechats"))
async def cmd_gamechats(message: Message, user: User | None, perms: set[str], session: Session) -> None:
    if await _deny_if_no_access(message, user, perms):
        return
    rows = g.list_game_chats(session)
    if not rows:
        await message.answer("Пока нет игровых чатов. Зайди в нужный чат/топик и напиши /allowgames.")
        return
    lines = ["🎮 <b>Игровые чаты</b>\n"]
    for r in rows:
        title = r.title or str(r.chat_id)
        topic = f" · топик {r.thread_id}" if r.thread_id else ""
        lines.append(f"• {title}{topic}")
    await message.answer("\n".join(lines))
