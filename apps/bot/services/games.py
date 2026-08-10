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
QUIZ: list[dict] = [
    {"q": "Сколько блоков в стопке (максимальный стак) в Minecraft?", "opts": ["16", "32", "64", "128"], "a": 2},
    {"q": "Из чего крафтится факел?", "opts": ["Уголь + палка", "Железо + палка", "Камень + уголь", "Дерево + уголь"], "a": 0},
    {"q": "Какой моб взрывается?", "opts": ["Зомби", "Крипер", "Скелет", "Паук"], "a": 1},
    {"q": "Сколько сердец (HP) у игрока по умолчанию?", "opts": ["10", "20", "30", "100"], "a": 1},
    {"q": "Что нужно, чтобы попасть в Нижний мир (Nether)?", "opts": ["Алмазы", "Обсидиан + огниво", "Эндер-жемчуг", "Золото"], "a": 1},
    {"q": "Какой инструмент нужен для добычи обсидиана?", "opts": ["Каменная кирка", "Железная кирка", "Алмазная кирка", "Деревянная кирка"], "a": 2},
    {"q": "Сколько эндер-глаз нужно для активации портала в Край?", "opts": ["9", "12", "16", "6"], "a": 1},
    {"q": "Что даёт зачарование «Аква-Аффинити»?", "opts": ["Скорость под водой", "Скорость копания под водой", "Дыхание под водой", "Ночное зрение"], "a": 1},
    {"q": "Какой моб роняет эндер-жемчуг?", "opts": ["Крипер", "Эндермен", "Иссушитель", "Гаст"], "a": 1},
    {"q": "Сколько золотых слитков в золотом блоке?", "opts": ["4", "6", "9", "16"], "a": 2},
]

EIGHTBALL = [
    "Бесспорно.", "Определённо да.", "Можешь быть уверен.", "Скорее всего.",
    "Хорошие перспективы.", "Знаки говорят «да».", "Пока не ясно, попробуй ещё.",
    "Спроси позже.", "Лучше не рассказывать.", "Сейчас нельзя предсказать.",
    "Даже не думай.", "Мой ответ — нет.", "По моим данным — нет.", "Весьма сомнительно.",
]
