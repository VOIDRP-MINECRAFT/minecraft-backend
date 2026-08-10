from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.telegram import TelegramGameChat, TelegramGameScore

DAILY_AMOUNT = 50
DAILY_COOLDOWN = timedelta(hours=24)

# In-process per-(chat,user,game) cooldowns (seconds since epoch of last use).
_cooldowns: dict[tuple[int, int, str], float] = {}


def check_cooldown(chat_id: int, user_id: int, game: str, seconds: int) -> int:
    """Return remaining cooldown seconds (0 if ready), and arm it when ready."""
    key = (chat_id, user_id, game)
    now = time.monotonic()
    last = _cooldowns.get(key, 0.0)
    remaining = int(seconds - (now - last))
    if remaining > 0:
        return remaining
    _cooldowns[key] = now
    return 0


# ── allowed game chats ───────────────────────────────────────────────────────
def is_game_chat(session: Session, chat_id: int, thread_id: int | None) -> bool:
    row = session.scalar(
        select(TelegramGameChat.id).where(
            TelegramGameChat.chat_id == chat_id,
            TelegramGameChat.thread_id.is_(thread_id) if thread_id is None
            else TelegramGameChat.thread_id == thread_id,
        )
    )
    return row is not None


def allow_game_chat(session: Session, chat_id: int, thread_id: int | None, title: str | None,
                    added_by: UUID | None) -> bool:
    """Returns True if newly added, False if already allowed."""
    if is_game_chat(session, chat_id, thread_id):
        return False
    session.add(TelegramGameChat(
        chat_id=chat_id, thread_id=thread_id, title=title, added_by_user_id=added_by,
    ))
    session.flush()
    return True


def disallow_game_chat(session: Session, chat_id: int, thread_id: int | None) -> bool:
    row = session.scalar(
        select(TelegramGameChat).where(
            TelegramGameChat.chat_id == chat_id,
            TelegramGameChat.thread_id.is_(thread_id) if thread_id is None
            else TelegramGameChat.thread_id == thread_id,
        )
    )
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def list_game_chats(session: Session) -> list[TelegramGameChat]:
    return list(session.scalars(select(TelegramGameChat).order_by(TelegramGameChat.created_at)).all())


# ── scores ───────────────────────────────────────────────────────────────────
def _score_row(session: Session, tg_id: int, chat_id: int, username: str | None) -> TelegramGameScore:
    row = session.scalar(
        select(TelegramGameScore).where(
            TelegramGameScore.telegram_user_id == tg_id, TelegramGameScore.chat_id == chat_id
        )
    )
    if row is None:
        row = TelegramGameScore(telegram_user_id=tg_id, chat_id=chat_id, telegram_username=username, score=0)
        session.add(row)
        session.flush()
    elif username and row.telegram_username != username:
        row.telegram_username = username
    return row


def add_score(session: Session, tg_id: int, chat_id: int, username: str | None, delta: int) -> int:
    row = _score_row(session, tg_id, chat_id, username)
    row.score = max(0, row.score + delta)
    session.flush()
    return row.score


def get_score(session: Session, tg_id: int, chat_id: int) -> int:
    row = session.scalar(
        select(TelegramGameScore).where(
            TelegramGameScore.telegram_user_id == tg_id, TelegramGameScore.chat_id == chat_id
        )
    )
    return row.score if row else 0


def rank_of(session: Session, tg_id: int, chat_id: int) -> int:
    my = get_score(session, tg_id, chat_id)
    higher = session.scalar(
        select(TelegramGameScore.id).where(
            TelegramGameScore.chat_id == chat_id, TelegramGameScore.score > my
        ).limit(1)
    )
    # cheap rank: count of strictly-higher + 1
    from sqlalchemy import func
    cnt = session.scalar(
        select(func.count()).select_from(TelegramGameScore).where(
            TelegramGameScore.chat_id == chat_id, TelegramGameScore.score > my
        )
    ) or 0
    return int(cnt) + 1 if (my > 0 or higher is not None) else 0


def top_scores(session: Session, chat_id: int, limit: int = 10) -> list[TelegramGameScore]:
    return list(session.scalars(
        select(TelegramGameScore)
        .where(TelegramGameScore.chat_id == chat_id, TelegramGameScore.score > 0)
        .order_by(TelegramGameScore.score.desc())
        .limit(limit)
    ).all())


def pvp_settle(
    session: Session, chat_id: int, *, winner_id: int, winner_name: str | None,
    loser_id: int, loser_name: str | None, reward: int,
) -> tuple[int, int]:
    """Competitive payout: the winner always gains ``reward``; the loser pays out
    of pocket only what they have (min(reward, balance)) — never going negative.
    If the loser is broke, nothing is taken but the winner still gets the reward.
    Returns (winner_gain, loser_loss)."""
    loser_bal = get_score(session, loser_id, chat_id)
    loss = min(reward, loser_bal)
    if loss:
        add_score(session, loser_id, chat_id, loser_name, -loss)
    add_score(session, winner_id, chat_id, winner_name, reward)
    return reward, loss


def solo_wager(
    session: Session, chat_id: int, tg_id: int, username: str | None, stake: int, gross_payout: int,
) -> int | None:
    """Solo house game. Deducts ``stake`` and credits ``gross_payout`` (0 = lost).
    Returns the new balance, or None if the player can't cover the stake."""
    bal = get_score(session, tg_id, chat_id)
    if stake > bal:
        return None
    return add_score(session, tg_id, chat_id, username, gross_payout - stake)


def claim_daily(session: Session, tg_id: int, chat_id: int, username: str | None) -> tuple[bool, int, int]:
    """(claimed, amount_or_score, wait_seconds)."""
    row = _score_row(session, tg_id, chat_id, username)
    now = datetime.now(timezone.utc)
    last = row.last_daily_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        ready_at = last + DAILY_COOLDOWN
        if now < ready_at:
            return (False, 0, int((ready_at - now).total_seconds()))
    row.last_daily_at = now
    row.score += DAILY_AMOUNT
    session.flush()
    return (True, DAILY_AMOUNT, 0)


# ── content ──────────────────────────────────────────────────────────────────
EIGHTBALL = [
    "Бесспорно.", "Определённо да.", "Можешь быть уверен.", "Скорее всего.",
    "Хорошие перспективы.", "Знаки говорят «да».", "Пока не ясно, попробуй ещё.",
    "Спроси позже.", "Лучше не рассказывать.", "Сейчас нельзя предсказать.",
    "Даже не думай.", "Мой ответ — нет.", "По моим данным — нет.", "Весьма сомнительно.",
]
