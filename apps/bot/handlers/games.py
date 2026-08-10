from __future__ import annotations

import asyncio
import random

from aiogram import Bot, F, Router
from aiogram.enums import ChatType, DiceEmoji
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.orm import Session

from apps.bot import texts
from apps.bot.keyboards import duel_kb, rps_kb
from apps.bot.services import games as g

router = Router(name="games")

# In-memory per-(chat, thread) round state.
_active_guess: dict[tuple, dict] = {}
# Pending PvP rock-paper-scissors games, keyed by (chat_id, prompt_message_id).
_active_rps: dict[tuple, dict] = {}

RPS_EMOJI = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

MIN_STAKE = 5
DUEL_DEFAULT = 30

GAMES_LIST = (
    "🎮 <b>Мини-игры VoidRP</b>\n"
    "Очки — <b>войды</b>. Их можно выиграть и проиграть (вплоть до 0). Стартовый доход — /daily.\n\n"
    "<b>На ставку (риск):</b>\n"
    "🎲 /dice &lt;ставка&gt; — кубик: 4–6 выигрыш, 1–3 проигрыш\n"
    "🎰 /slots &lt;ставка&gt; — слоты: три в ряд ×4, джекпот ×10\n\n"
    "<b>Против игроков</b> (ответом на игрока):\n"
    "⚔️ /duel &lt;ставка&gt; — дуэль на кубиках\n"
    "✊ /rps &lt;ставка&gt; — камень-ножницы-бумага\n"
    "Победитель забирает войды; проигравший отдаёт сколько есть (не в минус).\n\n"
    "<b>На умение / фан:</b>\n"
    "🔢 /guess — угадай число · 🎱 /8ball &lt;вопрос&gt;\n"
    "🎁 /daily — ежедневная награда · 🏆 /top · 💰 /me\n"
)


def _thread(message: Message) -> int | None:
    return message.message_thread_id if getattr(message, "is_topic_message", False) else None


def _key(chat_id: int, thread: int | None) -> tuple:
    return (chat_id, thread)


async def _guard(message: Message, session: Session) -> bool:
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


def _parse_stake(command: CommandObject, balance: int) -> tuple[int | None, str | None]:
    """Return (stake, error_message)."""
    if not command.args:
        return None, f"Укажи ставку: например <code>{command.command} 20</code>. Твой баланс: {balance}."
    raw = command.args.strip().split()[0]
    if not raw.isdigit():
        return None, "Ставка должна быть числом."
    stake = int(raw)
    if stake < MIN_STAKE:
        return None, f"Минимальная ставка — {MIN_STAKE} войдов."
    if stake > balance:
        return None, f"Недостаточно войдов. Твой баланс: {balance}. Возьми /daily."
    return stake, None


# ── Solo staked games ────────────────────────────────────────────────────────
@router.message(Command("dice"))
async def cmd_dice(message: Message, command: CommandObject, session: Session) -> None:
    if not await _guard(message, session):
        return
    bal = g.get_score(session, message.from_user.id, message.chat.id)
    stake, err = _parse_stake(command, bal)
    if err:
        await message.answer(err)
        return
    msg = await message.answer_dice(emoji=DiceEmoji.DICE)
    await asyncio.sleep(3.6)
    mult = {1: 0, 2: 0, 3: 0, 4: 1.5, 5: 2, 6: 2.5}[msg.dice.value]
    gross = int(stake * mult)
    total = g.solo_wager(session, message.chat.id, message.from_user.id, _uname(message), stake, gross)
    if gross:
        await message.answer(f"🎲 {msg.dice.value} → выигрыш <b>+{gross - stake}</b>! Баланс: <b>{total}</b>.")
    else:
        await message.answer(f"🎲 {msg.dice.value} → мимо, −{stake}. Баланс: <b>{total}</b>.")


@router.message(Command("slots"))
async def cmd_slots(message: Message, command: CommandObject, session: Session) -> None:
    if not await _guard(message, session):
        return
    bal = g.get_score(session, message.from_user.id, message.chat.id)
    stake, err = _parse_stake(command, bal)
    if err:
        await message.answer(err)
        return
    msg = await message.answer_dice(emoji=DiceEmoji.SLOT_MACHINE)
    await asyncio.sleep(2.2)
    v = msg.dice.value
    if v == 64:
        mult, note = 10, "🎉 ДЖЕКПОТ 777!"
    elif v in (1, 22, 43):
        mult, note = 4, "🔥 Три в ряд!"
    else:
        mult, note = 0, "Мимо"
    gross = stake * mult
    total = g.solo_wager(session, message.chat.id, message.from_user.id, _uname(message), stake, gross)
    if gross:
        await message.answer(f"🎰 {note} <b>+{gross - stake}</b> войдов! Баланс: <b>{total}</b>.")
    else:
        await message.answer(f"🎰 {note}, −{stake}. Баланс: <b>{total}</b>.")


@router.message(Command("rps"))
async def cmd_rps(message: Message, command: CommandObject, session: Session) -> None:
    if not await _guard(message, session):
        return
    reply = message.reply_to_message
    if reply is None or reply.from_user is None or reply.from_user.is_bot:
        await message.answer("✊ Ответь этой командой на сообщение игрока. Ставка: <code>/rps 30</code>.")
        return
    if reply.from_user.id == message.from_user.id:
        await message.answer("Сам с собой? 🙃")
        return
    reward = DUEL_DEFAULT
    if command.args and command.args.strip().split()[0].isdigit():
        reward = max(MIN_STAKE, int(command.args.strip().split()[0]))
    challenger, opponent = message.from_user, reply.from_user
    base = (
        f"✊ <b>{challenger.full_name}</b> vs <b>{opponent.full_name}</b> — "
        f"камень-ножницы-бумага на <b>{reward}</b> войдов!\n"
        f"Оба жмите свой ход — соперник его не увидит. Победитель забирает войды."
    )
    prompt = await message.answer(base, reply_markup=rps_kb())
    _active_rps[(message.chat.id, prompt.message_id)] = {
        "challenger": challenger.id,
        "opponent": opponent.id,
        "reward": reward,
        "base": base,
        "choices": {},
        "names": {challenger.id: challenger.full_name, opponent.id: opponent.full_name},
        "unames": {
            challenger.id: challenger.username or challenger.full_name,
            opponent.id: opponent.username or opponent.full_name,
        },
    }


@router.callback_query(F.data.startswith("rps:"))
async def on_rps(cb: CallbackQuery, session: Session) -> None:
    key = (cb.message.chat.id, cb.message.message_id)
    game = _active_rps.get(key)
    if game is None:
        await cb.answer("Эта партия уже завершена.")
        return
    uid = cb.from_user.id
    if uid not in (game["challenger"], game["opponent"]):
        await cb.answer("Это не твоя партия 🙂", show_alert=True)
        return
    if uid in game["choices"]:
        await cb.answer("Ты уже сделал ход.")
        return
    choice = cb.data.split(":", 1)[1]
    game["choices"][uid] = choice
    await cb.answer(f"Твой ход: {RPS_EMOJI[choice]}")

    if len(game["choices"]) < 2:
        await cb.message.edit_text(
            game["base"] + f"\n\n✅ {game['names'][uid]} сделал ход. Ждём соперника…",
            reply_markup=rps_kb(),
        )
        return

    _active_rps.pop(key, None)
    c_id, o_id = game["challenger"], game["opponent"]
    cc, oc = game["choices"][c_id], game["choices"][o_id]
    head = f"✊ {game['names'][c_id]}: {RPS_EMOJI[cc]}  ·  {game['names'][o_id]}: {RPS_EMOJI[oc]}"
    if cc == oc:
        await cb.message.edit_text(f"{head}\n🤝 Ничья! Переиграйте: /rps {game['reward']}")
        return
    winner_id, loser_id = (c_id, o_id) if RPS_BEATS[cc] == oc else (o_id, c_id)
    gain, loss = g.pvp_settle(
        session, cb.message.chat.id,
        winner_id=winner_id, winner_name=game["unames"][winner_id],
        loser_id=loser_id, loser_name=game["unames"][loser_id], reward=game["reward"],
    )
    w_total = g.get_score(session, winner_id, cb.message.chat.id)
    note = f"забрал {loss}" if loss >= gain else (f"получил {gain} (у соперника было лишь {loss})" if loss else f"получил {gain} (у соперника пусто)")
    await cb.message.edit_text(f"{head}\n🏆 Победил <b>{game['names'][winner_id]}</b>, {note}! Баланс: <b>{w_total}</b>.")


# ── PvP: duel ────────────────────────────────────────────────────────────────
@router.message(Command("duel"))
async def cmd_duel(message: Message, command: CommandObject, session: Session) -> None:
    if not await _guard(message, session):
        return
    reply = message.reply_to_message
    if reply is None or reply.from_user is None or reply.from_user.is_bot:
        await message.answer("⚔️ Ответь этой командой на сообщение игрока, которого вызываешь. Ставка: <code>/duel 50</code>.")
        return
    if reply.from_user.id == message.from_user.id:
        await message.answer("Сам с собой? 🙃")
        return
    reward = DUEL_DEFAULT
    if command.args and command.args.strip().split()[0].isdigit():
        reward = max(MIN_STAKE, int(command.args.strip().split()[0]))
    await message.answer(
        f"⚔️ <b>{message.from_user.full_name}</b> вызывает <b>{reply.from_user.full_name}</b> на дуэль-кубик!\n"
        f"Победитель получает <b>{reward}</b> войдов, проигравший отдаёт сколько есть (не в минус).",
        reply_markup=duel_kb(message.from_user.id, reply.from_user.id, reward),
    )


@router.callback_query(F.data.startswith("duel:"))
async def on_duel(cb: CallbackQuery, session: Session, bot: Bot) -> None:
    _, action, challenger_id, opponent_id, reward = cb.data.split(":")
    challenger_id, opponent_id, reward = int(challenger_id), int(opponent_id), int(reward)
    if cb.from_user.id != opponent_id:
        await cb.answer("Это вызов не тебе 🙂", show_alert=True)
        return
    if action == "decline":
        await cb.message.edit_text("🏳 Дуэль отклонена.")
        await cb.answer()
        return
    await cb.answer("Бросаем кубики!")
    thread = cb.message.message_thread_id if getattr(cb.message, "is_topic_message", False) else None
    d1 = await bot.send_dice(cb.message.chat.id, emoji=DiceEmoji.DICE, message_thread_id=thread)
    d2 = await bot.send_dice(cb.message.chat.id, emoji=DiceEmoji.DICE, message_thread_id=thread)
    await asyncio.sleep(3.6)
    v1, v2 = d1.dice.value, d2.dice.value
    if v1 == v2:
        await cb.message.answer(f"⚔️ {v1}:{v2} — ничья! Переиграйте: /duel {reward}")
        return
    winner_id, loser_id = (challenger_id, opponent_id) if v1 > v2 else (opponent_id, challenger_id)
    winner = (await bot.get_chat_member(cb.message.chat.id, winner_id)).user
    loser = (await bot.get_chat_member(cb.message.chat.id, loser_id)).user
    gain, loss = g.pvp_settle(
        session, cb.message.chat.id,
        winner_id=winner_id, winner_name=winner.username or winner.full_name,
        loser_id=loser_id, loser_name=loser.username or loser.full_name, reward=reward,
    )
    w_total = g.get_score(session, winner_id, cb.message.chat.id)
    note = f"забрал {loss} у соперника" if loss >= gain else (f"получил {gain} (у соперника было лишь {loss})" if loss else f"получил {gain} (у соперника пусто)")
    await cb.message.answer(f"⚔️ {v1}:{v2} — победил <b>{winner.full_name}</b>, {note}! Баланс: <b>{w_total}</b>.")


# ── Skill games ──────────────────────────────────────────────────────────────
@router.message(Command("guess"))
async def cmd_guess(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    key = _key(message.chat.id, _thread(message))
    if key in _active_guess:
        await message.answer("🔢 Игра уже идёт — присылай число 1–100!")
        return
    _active_guess[key] = {"number": random.randint(1, 100)}
    await message.answer("🔢 Я загадал число 1–100. Пишите варианты числом — подскажу «больше/меньше». Победитель получит <b>25</b> войдов!")


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
        total = g.add_score(session, message.from_user.id, message.chat.id, _uname(message), 25)
        await message.reply(f"🎯 В точку! Это было <b>{target}</b>. +25 войдов. Баланс: <b>{total}</b>.")


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


@router.message(Command("games"))
async def cmd_games(message: Message, session: Session) -> None:
    if not await _guard(message, session):
        return
    await message.answer(GAMES_LIST)


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
