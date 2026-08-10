from __future__ import annotations

from io import BytesIO
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.services.news_service import NewsService
from apps.bot import texts
from apps.bot.keyboards import category_kb, servers_kb, targets_kb
from apps.bot.permissions import can_publish_any_news
from apps.bot.services.tg_news import (
    entities_to_markdown,
    make_excerpt,
    make_title,
    save_cover_from_bytes,
)
from apps.bot.states import NewsDraft

router = Router(name="news")


@router.message(StateFilter(None), F.chat.type == ChatType.PRIVATE)
async def on_prepared_message(message: Message, state: FSMContext, user: User | None, perms: set[str]) -> None:
    """Any non-command content message from a news-capable user starts a draft."""
    if user is None or not can_publish_any_news(perms):
        return
    if message.text and message.text.startswith("/"):
        return
    text = message.text or message.caption
    photo = message.photo[-1] if message.photo else None
    if not text and not photo:
        return
    entities = message.entities or message.caption_entities or []
    await state.update_data(
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        body_md=entities_to_markdown(text, entities),
        excerpt=make_excerpt(text),
        default_title=make_title(text),
        photo_file_id=(photo.file_id if photo else None),
        targets={"site": True, "telegram": True, "discord": True},
    )
    await state.set_state(NewsDraft.waiting_title)
    await message.answer(texts.NEWS_GOT_MESSAGE + "\n\n<i>Или отправь «-», чтобы взять первую строку.</i>")


@router.message(NewsDraft.waiting_title, F.text)
async def on_title(message: Message, state: FSMContext, session: Session) -> None:
    title = message.text.strip()
    data = await state.get_data()
    if title == "-":
        title = data.get("default_title") or "Новость"
    if len(title) > 200:
        await message.answer(texts.NEWS_TITLE_TOO_LONG)
        return
    await state.update_data(title=title)
    servers = list(session.scalars(select(GameServer).order_by(GameServer.sort_order)).all())
    if not servers:
        await message.answer(texts.NEWS_NO_SERVERS)
        await state.clear()
        return
    await state.set_state(NewsDraft.waiting_server)
    await message.answer(texts.NEWS_ASK_SERVER, reply_markup=servers_kb(servers))


@router.callback_query(NewsDraft.waiting_server, F.data.startswith("news:srv:"))
async def on_server(cb: CallbackQuery, state: FSMContext, perms: set[str]) -> None:
    await state.update_data(server_id=cb.data.split(":", 2)[2])
    allowed = []
    if "news.updates.manage" in perms:
        allowed.append("update")
    if "news.media.manage" in perms:
        allowed.append("media")
    await state.set_state(NewsDraft.waiting_category)
    await cb.message.edit_text(texts.NEWS_ASK_CATEGORY, reply_markup=category_kb(allowed))
    await cb.answer()


@router.callback_query(NewsDraft.waiting_category, F.data.startswith("news:cat:"))
async def on_category(cb: CallbackQuery, state: FSMContext, perms: set[str]) -> None:
    cat = cb.data.split(":", 2)[2]
    if cat not in ("update", "media") or f"news.{'updates' if cat == 'update' else 'media'}.manage" not in perms:
        await cb.answer("Нет прав на эту категорию", show_alert=True)
        return
    await state.update_data(category=cat)
    data = await state.get_data()
    await state.set_state(NewsDraft.waiting_targets)
    await cb.message.edit_text(texts.NEWS_ASK_TARGETS, reply_markup=targets_kb(data["targets"]))
    await cb.answer()


@router.callback_query(NewsDraft.waiting_targets, F.data.startswith("news:tgt:"))
async def on_toggle_target(cb: CallbackQuery, state: FSMContext) -> None:
    name = cb.data.split(":", 2)[2]
    data = await state.get_data()
    targets = data["targets"]
    targets[name] = not targets.get(name, False)
    await state.update_data(targets=targets)
    await cb.message.edit_reply_markup(reply_markup=targets_kb(targets))
    await cb.answer()


@router.callback_query(F.data == "news:cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text(texts.NEWS_CANCELLED)
    await cb.answer()


@router.callback_query(NewsDraft.waiting_targets, F.data == "news:go")
async def on_publish(cb: CallbackQuery, state: FSMContext, session: Session, user: User, bot: Bot) -> None:
    data = await state.get_data()
    targets = data["targets"]
    if not any(targets.values()):
        await cb.answer("Выбери хотя бы один канал", show_alert=True)
        return
    await cb.message.edit_text(texts.NEWS_PUBLISHING)
    await cb.answer()

    server = session.get(GameServer, UUID(data["server_id"]))
    category = data["category"]
    service = NewsService(session, server)
    lines: list[str] = []

    # Cover from the prepared photo (only when publishing to the site).
    need_post = targets["site"] or targets["discord"]
    cover_url = None
    if need_post and data.get("photo_file_id"):
        try:
            f = await bot.get_file(data["photo_file_id"])
            buf = BytesIO()
            await bot.download_file(f.file_path, destination=buf)
            cover_url = save_cover_from_bytes(buf.getvalue())
        except Exception:
            cover_url = None

    post = None
    if need_post:
        post = service.create(
            category=category, title=data["title"], summary=data.get("excerpt"),
            body=data.get("body_md") or "", cover_image_url=cover_url,
            is_published=True, author=user,
        )
        if targets["site"]:
            lines.append(f"🌐 Сайт: ✅ /news/{post.slug}")

    # Telegram — exact copy of the prepared message into each configured target.
    if targets["telegram"]:
        chans = server.channels_for(category)["telegram"]
        if not chans:
            lines.append("📨 Telegram: ❌ каналы не заданы для категории")
        else:
            ok = 0
            for tgt in chans:
                chat = (tgt or {}).get("chat_id")
                if not chat:
                    continue
                try:
                    await bot.copy_message(
                        chat_id=chat, from_chat_id=data["from_chat_id"],
                        message_id=data["message_id"],
                        message_thread_id=(tgt or {}).get("thread_id"),
                    )
                    ok += 1
                except Exception:
                    pass
            if post is not None and ok:
                post.posted_telegram = True
            lines.append(f"📨 Telegram: {'✅ ' + str(ok) + ' канал(ов)' if ok else '❌ не отправлено'}")

    # Discord — reuse the news service embed path.
    if targets["discord"] and post is not None:
        res = service.broadcast(post, to_telegram=False, to_discord=True)
        if res.get("discord_ok"):
            lines.append("💬 Discord: ✅")
        else:
            chans = server.channels_for(category)["discord"]
            lines.append("💬 Discord: ❌ " + ("webhook не задан" if not chans else "не отправлено"))

    session.commit()
    await state.clear()
    header = f"<b>«{data['title']}»</b> → <b>{server.name}</b> · {'Обновления' if category == 'update' else 'Новости'}\n\n"
    await bot.send_message(cb.message.chat.id, header + "\n".join(lines))
