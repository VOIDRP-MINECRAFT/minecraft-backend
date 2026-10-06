"""Running a partner server from Telegram: ``/servers`` and the buttons under integration notices.

* ``/servers`` — the servers this person runs; one of them opens as a card (state, players, TPS,
  uptime, connection grade, waiting updates, the top advice) with buttons.
* ``int:s:<slug>`` — open / refresh the card; ``int:au:<slug>`` — auto-update on/off
  (``integration.config``); ``int:t:<slug>`` — «проверить связь» through the server console.
* ``intmute:<slug>`` — under an outage notice: an hour of silence; ``intunmute`` brings them back.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import integration_brief as brief
from apps.api.app.core import integration_notices
from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User

router = Router(name="integration")
MSK = timedelta(hours=3)


def _muted_until(user: User) -> str | None:
    if not integration_notices._muted(user):
        return None
    from datetime import datetime

    return (datetime.fromisoformat(integration_notices.prefs(user)["mute_until"]) + MSK).strftime("%H:%M МСК")


def _card_kb(user: User, server: GameServer, data: dict, many: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data=f"int:s:{server.slug}")
    if brief.can(user, server, "integration.config"):
        on = (data.get("settings") or {}).get("auto_update")
        kb.button(text="🔁 Автообновление: выкл" if on else "🔁 Автообновление: вкл", callback_data=f"int:au:{server.slug}")
        if any(r["fresh"] and (r.get("modules") or {}).get("console", {}).get("ok") for r in data.get("reports") or []):
            kb.button(text="🩺 Проверить связь", callback_data=f"int:t:{server.slug}")
    if _muted_until(user):
        kb.button(text="🔔 Вернуть оповещения", callback_data="intunmute")
    for text, url in brief.links(server, data):
        kb.button(text=text, url=url)
    if many:
        kb.button(text="← Все серверы", callback_data="int:list")
    kb.adjust(1)
    return kb.as_markup()


async def _overview(session: Session, server: GameServer) -> dict:
    # The outside ping and the queries are blocking: keep them off the bot's event loop.
    return await asyncio.to_thread(brief.overview, session, server)


async def _show_list(target: Message, user: User, session: Session, edit: bool) -> None:
    servers = brief.servers_for(session, user)
    if not servers:
        text = ("У тебя нет серверов в «Интеграции». Если ты ведёшь сервер партнёра, попроси владельца "
                "выдать право «Интеграция — просмотр».")
        await (target.edit_text(text) if edit else target.answer(text))
        return
    if len(servers) == 1:
        await _show_card(target, user, session, servers[0], edit, many=False)
        return
    lines = ["🖥 <b>Твои серверы</b>\n"]
    kb = InlineKeyboardBuilder()
    for s in servers:
        data = await _overview(session, s)
        emoji, words = brief.state_of(data)
        grade = (data.get("health") or {}).get("grade")
        lines.append(f"{emoji} <b>{s.name}</b> — {words}" + (f" · {grade}" if grade else ""))
        kb.button(text=f"{emoji} {s.name}", callback_data=f"int:s:{s.slug}")
    kb.adjust(1)
    text = "\n".join(lines)
    await (target.edit_text(text, reply_markup=kb.as_markup()) if edit else target.answer(text, reply_markup=kb.as_markup()))


async def _show_card(target: Message, user: User, session: Session, server: GameServer, edit: bool, many: bool) -> None:
    data = await _overview(session, server)
    text = brief.card(server, data, muted_until=_muted_until(user))
    kb = _card_kb(user, server, data, many)
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception as exc:  # noqa: BLE001 — "message is not modified" on a refresh with no change
            if "not modified" not in str(exc):
                raise
    else:
        await target.answer(text, reply_markup=kb, disable_web_page_preview=True)


def _server(session: Session, user: User, slug: str) -> GameServer | None:
    server = session.scalar(select(GameServer).where(GameServer.slug == slug))
    if server is None or not brief.can(user, server, "integration.view"):
        return None
    return server


@router.message(Command("servers"))
async def cmd_servers(message: Message, user: User | None, session: Session) -> None:
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Состояние серверов показываю в личке — напиши мне /servers там.")
        return
    if user is None:
        await message.answer("Сначала привяжи аккаунт VoidRP: /start")
        return
    await _show_list(message, user, session, edit=False)


@router.callback_query(F.data == "int:list")
async def on_list(cb: CallbackQuery, user: User | None, session: Session) -> None:
    if user is None:
        await cb.answer("Сначала привяжи аккаунт: /start", show_alert=True)
        return
    await cb.answer()
    await _show_list(cb.message, user, session, edit=True)


@router.callback_query(F.data.startswith("int:"))
async def on_server_action(cb: CallbackQuery, user: User | None, session: Session) -> None:
    if user is None:
        await cb.answer("Сначала привяжи аккаунт: /start", show_alert=True)
        return
    _, action, slug = (cb.data.split(":", 2) + [""])[:3]
    server = _server(session, user, slug)
    if server is None:
        await cb.answer("Нет доступа к этому серверу", show_alert=True)
        return
    many = len(brief.servers_for(session, user)) > 1

    if action == "au":
        if not brief.can(user, server, "integration.config"):
            await cb.answer("Нужно право «Интеграция — настройка»", show_alert=True)
            return
        on = not bool((server.integration_settings or {}).get("auto_update"))
        server.integration_settings = {**(server.integration_settings or {}), "auto_update": on}
        from apps.api.app.core.audit import record_audit

        record_audit(session, category="integration", action="settings", actor=user, target_type="server",
                     target_id=str(server.id), target_label=server.slug, server_id=server.id,
                     meta={"auto_update": on, "via": "telegram"})
        session.commit()
        await cb.answer("Автообновление включено — новые сборки поставятся сами" if on else "Автообновление выключено")
    elif action == "t":
        if not brief.can(user, server, "integration.config"):
            await cb.answer("Нужно право «Интеграция — настройка»", show_alert=True)
            return
        await cb.answer("Спрашиваю сервер…")
        from apps.api.app.core import server_console

        try:
            out = await asyncio.to_thread(server_console.run, server, "voidrp status", 10)
            await cb.message.answer(f"🩺 <b>{server.name}</b> ответил:\n<pre>{_esc(out)[:3500]}</pre>")
        except Exception as exc:  # noqa: BLE001
            await cb.message.answer(f"🩺 <b>{server.name}</b> не ответил: {_esc(str(exc))}")
        return
    else:
        await cb.answer()
    await _show_card(cb.message, user, session, server, edit=True, many=many)


def _esc(text: str) -> str:
    import html

    return html.escape(text or "")


@router.callback_query(F.data.startswith("intmute:"))
async def on_mute(cb: CallbackQuery, user: User | None, session: Session) -> None:
    if user is None:
        await cb.answer("Сначала привяжи аккаунт: /start", show_alert=True)
        return
    until = utc_now() + timedelta(hours=1)
    db_user = session.get(User, user.id)
    db_user.integration_notify = {**(db_user.integration_notify or {}), "mute_until": until.isoformat()}
    session.commit()
    await cb.answer(f"Тишина до {(until + MSK).strftime('%H:%M')} МСК — о новых сбоях не напишу", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔔 Вернуть оповещения", callback_data="intunmute")
    try:
        await cb.message.edit_reply_markup(reply_markup=kb.as_markup())
    except Exception:  # noqa: BLE001 — an old message may not be editable any more
        pass


@router.callback_query(F.data == "intunmute")
async def on_unmute(cb: CallbackQuery, user: User | None, session: Session) -> None:
    if user is None:
        await cb.answer("Сначала привяжи аккаунт: /start", show_alert=True)
        return
    db_user = session.get(User, user.id)
    prefs = dict(db_user.integration_notify or {})
    prefs.pop("mute_until", None)
    db_user.integration_notify = prefs
    session.commit()
    await cb.answer("Оповещения о сбоях снова включены")
    rows = (cb.message.reply_markup.inline_keyboard if cb.message.reply_markup else [])
    kept = [r for r in rows if not any(b.callback_data == "intunmute" for b in r)]
    try:
        await cb.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=kept) if kept else None)
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == "remind:off")
async def on_remind_off(cb: CallbackQuery, user: User | None, session: Session) -> None:
    """Under the second-day reminder (core/retention.py): never send it again."""
    if user is None:
        await cb.answer("Аккаунт не привязан", show_alert=True)
        return
    from apps.api.app.models.retention import PlayerReminder

    if not session.scalar(select(PlayerReminder.id).where(PlayerReminder.user_id == user.id, PlayerReminder.kind == "optout")):
        session.add(PlayerReminder(user_id=user.id, kind="optout", sent=False))
        session.commit()
    await cb.answer("Хорошо, больше не напомню")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
