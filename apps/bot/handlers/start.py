from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.orm import Session

from apps.api.app.models.user import User
from apps.bot import texts
from apps.bot.keyboards import link_kb
from apps.bot.permissions import can_manage_games, can_publish_any_news
from apps.bot.services.linking import issue_link_token

router = Router(name="start")


def _roles_line(user: User, perms: set[str]) -> str:
    if user.is_admin:
        return "Роль: <b>админ</b> (полный доступ)."
    tags = []
    if can_publish_any_news(perms):
        tags.append("новости")
    if can_manage_games(perms):
        tags.append("игры")
    if tags:
        return "Роль: <b>модератор</b> — " + ", ".join(tags) + "."
    return "Роль: обычный пользователь (в боте доступны игры в разрешённых чатах)."


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, user: User | None, perms: set[str], session: Session) -> None:
    if user is not None:
        name = user.telegram_username or user.site_login
        await message.answer(
            texts.WELCOME_LINKED.format(name=name, roles=_roles_line(user, perms)),
        )
        return
    url = issue_link_token(session, message.from_user.id, message.from_user.username)
    await message.answer(texts.WELCOME_UNLINKED, reply_markup=link_kb(url))
    await message.answer(texts.LINK_HINT)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, user: User | None, perms: set[str]) -> None:
    if user is None:
        await message.answer(texts.WHOAMI_UNLINKED)
        return
    lines = [f"👤 <b>{user.site_login}</b>", _roles_line(user, perms)]
    if perms and not user.is_admin:
        lines.append("\nПрава: <code>" + ", ".join(sorted(perms)) + "</code>")
    await message.answer("\n".join(lines))


@router.message(Command("help"))
async def cmd_help(message: Message, user: User | None, perms: set[str]) -> None:
    parts = [texts.HELP_BASE]
    if user is not None and can_publish_any_news(perms):
        parts.append(texts.HELP_NEWS)
    if user is not None and can_manage_games(perms):
        parts.append(texts.HELP_GAMES_ADMIN)
    parts.append(texts.HELP_GAMES_PLAYER)
    await message.answer("".join(parts))
