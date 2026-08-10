from __future__ import annotations

import asyncio
import random

from aiogram import Bot, F, Router
from aiogram.enums import ChatType, DiceEmoji
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.orm import Session

from apps.bot import texts
from apps.bot.keyboards import duel_kb, quiz_kb, rps_kb
from apps.bot.services import games as g

router = Router(name="games")

# In-memory per-(chat, thread) round state.
_active_guess: dict[tuple, dict] = {}
_active_quiz: dict[tuple, dict] = {}

GAMES_LIST = (
    "🎮 <b>Мини-игры VoidRP</b>\n\n"
    "🎲 /dice — бросок кубика (очки = ×2 значения)\n"
    "🎰 /slots — слот-машина, три в ряд = джекпот\n"
    "🔢 /guess — угадай число 1–100\n"
    "🧠 /quiz — викторина по Minecraft\n"
    "⚔️ /duel — дуэль (ответом на сообщение игрока)\n"
    "✊ /rps — камень-ножницы-бумага\n"
    "🎱 /8ball &lt;вопрос&gt; — магический шар\n"
    "🎁 /daily — ежедневная награда\n"
    "🏆 /top — топ игроков · /me — мой счёт\n"
)


def _thread(message: Message) -> int | None:
    return message.message_thread_id if getattr(message, "is_topic_message", False) else None


def _key(chat_id: int, thread: int | None) -> tuple:
    return (chat_id, thread)


async def _guard(message: Message, session: Session) -> bool:
    """True if games are allowed here; else nudge and return False."""
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("🎮 Игры доступны в игровых чатах сервера, не в личке.")
        return False
    if not g.is_game_chat(session, message.chat.id, _thread(message)):
        await message.answer(texts.GAMES_NOT_ALLOWED)
        return False
    return True


def _uname(message: Message) -> str | None:
    u = message.from_user
    return u.username or (u.full_name if u else None)


@router.message(Command("games"))
async def cmd_games(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    await message.answer(GAMES_LIST)


@router.message(Command("dice"))
async def cmd_dice(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    wait = g.check_cooldown(message.chat.id, message.from_user.id, "dice", 60)
    if wait:
        await message.answer(texts.COOLDOWN.format(sec=wait))
        return
    msg = await message.answer_dice(emoji=DiceEmoji.DICE)
    await asyncio.sleep(3.6)
    reward = msg.dice.value * 2
    total = g.add_score(session, message.from_user.id, message.chat.id, _uname(message), reward)
    await message.answer(f"🎲 {msg.dice.value} → +{reward} войдов. Баланс: <b>{total}</b>.")


@router.message(Command("slots"))
async def cmd_slots(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    wait = g.check_cooldown(message.chat.id, message.from_user.id, "slots", 60)
    if wait:
        await message.answer(texts.COOLDOWN.format(sec=wait))
        return
    msg = await message.answer_dice(emoji=DiceEmoji.SLOT_MACHINE)
    await asyncio.sleep(2.2)
    v = msg.dice.value
    if v == 64:
        reward, note = 150, "🎉 ДЖЕКПОТ 777!"
    elif v in (1, 22, 43):
        reward, note = 60, "🔥 Три в ряд!"
    else:
        reward, note = 5, "Почти!"
    total = g.add_score(session, message.from_user.id, message.chat.id, _uname(message), reward)
    await message.answer(f"🎰 {note} +{reward} войдов. Баланс: <b>{total}</b>.")


@router.message(Command("guess"))
async def cmd_guess(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    key = _key(message.chat.id, _thread(message))
    if key in _active_guess:
        await message.answer("🔢 Игра уже идёт — присылай число 1–100!")
        return
    _active_guess[key] = {"number": random.randint(1, 100)}
    await message.answer("🔢 Я загадал число от 1 до 100. Пишите варианты числом — подскажу «больше/меньше». Победитель получит <b>40</b> войдов!")


@router.message(F.text.regexp(r"^\d{1,3}$"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_guess_number(message: Message, session: Session) -> None:
    key = _key(message.chat.id, _thread(message))
    game = _active_guess.get(key)
    if game is None:
        return
    n = int(message.text)
    if not 1 <= n <= 100:
        return
    target = game["number"]
    if n < target:
        await message.reply("📈 Больше!")
    elif n > target:
        await message.reply("📉 Меньше!")
    else:
        _active_guess.pop(key, None)
        total = g.add_score(session, message.from_user.id, message.chat.id, _uname(message), 40)
        await message.reply(f"🎯 В точку! Это было <b>{target}</b>. +40 войдов. Баланс: <b>{total}</b>.")


@router.message(Command("quiz"))
async def cmd_quiz(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    key = _key(message.chat.id, _thread(message))
    if key in _active_quiz:
        await message.answer("🧠 Вопрос уже висит — отвечай на него!")
        return
    q = random.choice(g.QUIZ)
    _active_quiz[key] = {"a": q["a"], "answered": False}
    await message.answer(f"🧠 <b>{q['q']}</b>\nПервый верный ответ — +15 войдов.", reply_markup=quiz_kb(q["opts"]))


@router.callback_query(F.data.startswith("quiz:"))
async def on_quiz_answer(cb: CallbackQuery, session: Session) -> None:
    key = _key(cb.message.chat.id, cb.message.message_thread_id if getattr(cb.message, "is_topic_message", False) else None)
    game = _active_quiz.get(key)
    if game is None or game["answered"]:
        await cb.answer("Уже отвечено 🙂")
        return
    idx = int(cb.data.split(":", 1)[1])
    if idx != game["a"]:
        await cb.answer("Мимо ❌")
        return
    game["answered"] = True
    _active_quiz.pop(key, None)
    total = g.add_score(session, cb.from_user.id, cb.message.chat.id, cb.from_user.username or cb.from_user.full_name, 15)
    await cb.message.edit_text(f"🧠 Верно! 🏆 <b>{cb.from_user.full_name}</b> +15 войдов (баланс {total}).")
    await cb.answer("Правильно! +15")


@router.message(Command("rps"))
async def cmd_rps(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    await message.answer("✊ Твой ход:", reply_markup=rps_kb())


@router.callback_query(F.data.startswith("rps:"))
async def on_rps(cb: CallbackQuery, session: Session) -> None:
    choice = cb.data.split(":", 1)[1]
    bot_choice = random.choice(["rock", "scissors", "paper"])
    beats = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
    emoji = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
    if choice == bot_choice:
        res = "Ничья 🤝"
    elif beats[choice] == bot_choice:
        total = g.add_score(session, cb.from_user.id, cb.message.chat.id, cb.from_user.username or cb.from_user.full_name, 10)
        res = f"Ты выиграл! +10 войдов (баланс {total}) 🎉"
    else:
        res = "Я выиграл 😎"
    await cb.message.edit_text(f"Ты: {emoji[choice]}  Я: {emoji[bot_choice]}\n{res}")
    await cb.answer()


@router.message(Command("duel"))
async def cmd_duel(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    reply = message.reply_to_message
    if reply is None or reply.from_user is None or reply.from_user.is_bot:
        await message.answer("⚔️ Ответь этой командой на сообщение игрока, которого вызываешь.")
        return
    if reply.from_user.id == message.from_user.id:
        await message.answer("Сам с собой? 🙃")
        return
    await message.answer(
        f"⚔️ <b>{message.from_user.full_name}</b> вызывает <b>{reply.from_user.full_name}</b> на дуэль-кубик! Победитель +30 войдов.",
        reply_markup=duel_kb(message.from_user.id, reply.from_user.id),
    )


@router.callback_query(F.data.startswith("duel:"))
async def on_duel(cb: CallbackQuery, session: Session, bot: Bot) -> None:
    parts = cb.data.split(":")
    action, challenger_id, opponent_id = parts[1], int(parts[2]), int(parts[3])
    if cb.from_user.id != opponent_id:
        await cb.answer("Это вызов не тебе 🙂", show_alert=True)
        return
    if action == "decline":
        await cb.message.edit_text("🏳 Дуэль отклонена.")
        await cb.answer()
        return
    await cb.answer("Бросаем кубики!")
    d1 = await bot.send_dice(cb.message.chat.id, emoji=DiceEmoji.DICE, message_thread_id=cb.message.message_thread_id)
    d2 = await bot.send_dice(cb.message.chat.id, emoji=DiceEmoji.DICE, message_thread_id=cb.message.message_thread_id)
    await asyncio.sleep(3.6)
    v1, v2 = d1.dice.value, d2.dice.value
    if v1 == v2:
        await cb.message.answer(f"⚔️ {v1}:{v2} — ничья! Переиграйте.")
        return
    winner_id = challenger_id if v1 > v2 else opponent_id
    winner_name = (await bot.get_chat_member(cb.message.chat.id, winner_id)).user.full_name
    total = g.add_score(session, winner_id, cb.message.chat.id, None, 30)
    await cb.message.answer(f"⚔️ {v1}:{v2} — победил <b>{winner_name}</b>! +30 войдов (баланс {total}).")


@router.message(Command("8ball"))
async def cmd_8ball(message: Message, command: CommandObject, session: Session) -> None:
    if not await _guard(message, session):
        return
    if not command.args:
        await message.answer("🎱 Задай вопрос: <code>/8ball будет ли вайп?</code>")
        return
    await message.answer(f"🎱 {random.choice(g.EIGHTBALL)}")


@router.message(Command("daily"))
async def cmd_daily(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    ok, amount, wait = g.claim_daily(session, message.from_user.id, message.chat.id, _uname(message))
    if not ok:
        h = wait // 3600
        m = (wait % 3600) // 60
        await message.answer(f"🎁 Уже забирал. Возвращайся через {h} ч {m} мин.")
        return
    total = g.get_score(session, message.from_user.id, message.chat.id)
    await message.answer(f"🎁 +{amount} войдов! Баланс: <b>{total}</b>.")


@router.message(Command("me"))
async def cmd_me(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    score = g.get_score(session, message.from_user.id, message.chat.id)
    rank = g.rank_of(session, message.from_user.id, message.chat.id)
    tail = f" · место #{rank}" if rank else ""
    await message.answer(f"💰 <b>{message.from_user.full_name}</b>: {score} войдов{tail}.")


@router.message(Command("top"))
async def cmd_top(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    rows = g.top_scores(session, message.chat.id, 10)
    if not rows:
        await message.answer("🏆 Пока пусто — сыграйте во что-нибудь!")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ игроков</b>\n"]
    for i, r in enumerate(rows):
        badge = medals[i] if i < 3 else f"{i + 1}."
        name = ("@" + r.telegram_username) if r.telegram_username else "игрок"
        lines.append(f"{badge} {name} — <b>{r.score}</b>")
    await message.answer("\n".join(lines))
