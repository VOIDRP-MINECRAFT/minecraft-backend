"""Second-day return: bring a newcomer back the next day.

The funnel (core/funnel.py) showed the biggest loss between «entered a server» and «came back
another day». Three levers, per server (``game_servers.retention_settings``), the same on our
servers and on partners' — nothing new in the game plugins:

* **welcome** — on a player's first login to the server: a few lines in chat with the goals
  for the first day;
* **day2 reward** — on a login on a later calendar day (Moscow time) within ``window_days`` of
  the first: the reward commands (``give``, ``eco give``…), once per player and server;
* **reminder** — ~a day after the first login, if the player has not come back and linked
  Telegram: a message from @voidrp_bot that the reward is waiting (with «не напоминать»).
  No e-mail: there is no consent for promotional mail.

Logins come from ``PlayerActivityService.record`` — the play-ticket flow and the login plugins
call it on every server. Deliveries run through ``server_ops.rcon_command``: RCON on our
servers, the VoidRpPerms console queue on partners'. The worker (apps/worker/retention.py,
every minute) first sends the chat message: «no player found» means the player is not in game
yet — it tries again in two minutes, up to ~40 minutes.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_activity import PlayerServerActivity
from apps.api.app.models.retention import PlayerReminder, RetentionDelivery
from apps.api.app.models.user import User

log = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")
NICK = re.compile(r"^[A-Za-z0-9_]{1,16}$")
RETRY_EVERY = timedelta(minutes=2)
MAX_ATTEMPTS = 20
NOT_FOUND = ("no player was found", "no entity was found", "player not found", "игрок не найден", "игроки не найдены",
             "that player does not exist", "not online")
COMMAND_ERRORS = ("unknown command", "unknown or incomplete command", "incorrect argument", "неизвестная команда", "invalid")

# Commands a reward may run: the first word, and the player has to be in it. Anyone holding
# retention.manage should not get a back door to the whole console.
ALLOWED_COMMANDS = {"give", "minecraft:give", "eco", "money", "tellraw", "minecraft:tellraw", "title", "minecraft:title",
                    "effect", "minecraft:effect", "xp", "experience", "minecraft:xp", "minecraft:experience"}

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "window_days": 2,
    "reward_label": "награда за возвращение",
    "reward_message": "С возвращением, {player}! Держи награду за второй день — заходи и завтра.",
    "commands": ["minecraft:give {player} minecraft:golden_apple 3", "minecraft:give {player} minecraft:diamond 2"],
    "welcome_enabled": False,
    "welcome_lines": [
        "Добро пожаловать на {server}, {player}!",
        "Цель на сегодня: построй укрытие, найди железо и переночуй в безопасности.",
        "Зайди завтра — тебя будет ждать {reward}.",
    ],
    "reminder_enabled": True,
    "reminder_text": "Привет, {player}! Вчера ты впервые заходил на «{server}». Загляни сегодня — тебя ждёт {reward}.",
}


def settings(server: GameServer) -> dict[str, Any]:
    return {**DEFAULTS, **(getattr(server, "retention_settings", None) or {})}


def validate_command(cmd: str) -> str | None:
    """None when fine, else why not."""
    cmd = (cmd or "").strip()
    if not cmd:
        return "пустая команда"
    if "\n" in cmd or len(cmd) > 240:
        return "команда в одну строку, до 240 символов"
    if "{player}" not in cmd:
        return f"в команде нет {{player}}: «{cmd[:40]}»"
    first = cmd.lstrip("/").split()[0].lower()
    if first not in ALLOWED_COMMANDS:
        return f"«{first}» нельзя: разрешены give, eco/money, tellraw, title, effect, xp"
    return None


def _fill(text: str, *, player: str, server: str, reward: str) -> str:
    return (text or "").replace("{player}", player).replace("{server}", server).replace("{reward}", reward)


def _msk_day(dt: datetime):
    return dt.astimezone(MSK).date()


def _exists(session: Session, server_id: UUID, user_id: UUID, kind: str) -> bool:
    return session.scalar(select(RetentionDelivery.id).where(
        RetentionDelivery.server_id == server_id, RetentionDelivery.user_id == user_id, RetentionDelivery.kind == kind)) is not None


def on_login(session: Session, *, row: PlayerServerActivity, is_new: bool, now: datetime) -> None:
    """Called by PlayerActivityService.record on every login; queues what this login earns."""
    server = session.get(GameServer, row.server_id)
    if server is None:
        return
    cfg = settings(server)
    if not cfg["enabled"]:
        return
    nick = session.scalar(select(PlayerAccount.minecraft_nickname).where(PlayerAccount.user_id == row.user_id))
    if not nick or not NICK.match(nick):
        return
    if is_new:
        if cfg["welcome_enabled"] and not _exists(session, server.id, row.user_id, "welcome"):
            session.add(RetentionDelivery(server_id=server.id, user_id=row.user_id, nickname=nick, kind="welcome",
                                          deliver_after=now + timedelta(seconds=40)))
        return
    days = (_msk_day(now) - _msk_day(row.first_seen_at)).days
    if 1 <= days <= int(cfg["window_days"] or 2) and not _exists(session, server.id, row.user_id, "day2"):
        session.add(RetentionDelivery(server_id=server.id, user_id=row.user_id, nickname=nick, kind="day2",
                                      deliver_after=now + timedelta(seconds=40)))


def queue_test(session: Session, server: GameServer, nickname: str, actor: str) -> RetentionDelivery:
    row = RetentionDelivery(server_id=server.id, user_id=None, nickname=nickname, kind="test", deliver_after=utc_now(), created_by=actor)
    session.add(row)
    session.commit()
    return row


def _tellraw(player: str, text: str, color: str = "gold") -> str:
    return f"tellraw {player} " + json.dumps({"text": text, "color": color}, ensure_ascii=False)


def _run(server: GameServer, command: str) -> str:
    from apps.api.app.core import server_ops

    return server_ops.rcon_command(server, command, timeout=8.0) or ""


def deliver(session: Session, d: RetentionDelivery) -> None:
    server = session.get(GameServer, d.server_id)
    if server is None or not NICK.match(d.nickname):
        d.status, d.last_error = "failed", "сервер удалён или ник неверный"
        return
    cfg = settings(server)
    reward = cfg["reward_label"]
    fill = lambda t: _fill(t, player=d.nickname, server=server.name, reward=reward)  # noqa: E731
    lines = [fill(x) for x in cfg["welcome_lines"] if x.strip()] if d.kind == "welcome" else [fill(cfg["reward_message"])]
    d.attempts += 1
    try:
        # Is the player in game? «execute if entity» answers «Test passed / failed» on RCON and in
        # the VoidRpPerms queue alike (tellraw goes out as the console there, its answer is lost).
        probe = _run(server, f"execute if entity {d.nickname}").lower()
    except Exception as exc:  # noqa: BLE001 — RCON down, plugin silent: try again later
        _retry(d, f"сервер не ответил: {exc}"[:300])
        return
    if "failed" in probe or "не пройден" in probe or any(m in probe for m in NOT_FOUND):
        _retry(d, "игрок не в игре")
        return
    errors = []
    for i, line in enumerate(lines):
        try:
            _run(server, _tellraw(d.nickname, line, "gold" if i == 0 else "yellow"))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    if d.kind in ("day2", "test"):
        for cmd in cfg["commands"]:
            if validate_command(cmd):
                errors.append(f"пропущено: {validate_command(cmd)}")
                continue
            try:
                out = _run(server, fill(cmd).lstrip("/"))
                if any(m in out.lower() for m in COMMAND_ERRORS + NOT_FOUND):
                    errors.append(f"{cmd.split()[0]}: {out.strip()[:120]}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{cmd.split()[0]}: {exc}")
    d.status = "delivered"
    d.delivered_at = utc_now()
    d.last_error = "; ".join(errors)[:300] or None


def _retry(d: RetentionDelivery, why: str) -> None:
    d.last_error = why
    if d.attempts >= MAX_ATTEMPTS:
        d.status = "failed"
    else:
        d.deliver_after = utc_now() + RETRY_EVERY


def run_due(session: Session, limit: int = 50) -> int:
    rows = session.scalars(select(RetentionDelivery).where(RetentionDelivery.status == "pending", RetentionDelivery.deliver_after <= utc_now())
                           .order_by(RetentionDelivery.deliver_after).limit(limit)).all()
    for d in rows:
        try:
            deliver(session, d)
        except Exception as exc:  # noqa: BLE001 — one bad row never stops the rest
            log.exception("retention delivery %s failed", d.id)
            _retry(d, str(exc)[:300])
        session.commit()
    return len(rows)


def send_reminders(session: Session) -> int:
    """~A day after the first login, nobody came back: one Telegram message per player, ever."""
    from apps.api.app.core.integration_notices import _send

    now = utc_now()
    sent = 0
    for server in session.scalars(select(GameServer)).all():
        cfg = settings(server)
        if not (cfg["enabled"] and cfg["reminder_enabled"]):
            continue
        rows = session.execute(
            select(PlayerServerActivity, User, PlayerAccount.minecraft_nickname)
            .join(User, User.id == PlayerServerActivity.user_id)
            .join(PlayerAccount, PlayerAccount.user_id == User.id)
            .where(PlayerServerActivity.server_id == server.id,
                   PlayerServerActivity.first_seen_at.between(now - timedelta(hours=30), now - timedelta(hours=20)),
                   User.telegram_user_id.is_not(None), User.is_active.is_(True))
        ).all()
        for act, user, nick in rows:
            if _msk_day(act.last_seen_at) != _msk_day(act.first_seen_at):
                continue  # already came back
            done = session.scalar(select(func.count()).select_from(PlayerReminder).where(
                PlayerReminder.user_id == user.id, PlayerReminder.kind.in_(("day2", "optout"))))
            if done:
                continue
            text = html.escape(_fill(cfg["reminder_text"], player=nick or user.site_login, server=server.name, reward=cfg["reward_label"]))
            ok = _send(user.telegram_user_id, text, callbacks=[("🔕 Не напоминать", "remind:off")])
            session.add(PlayerReminder(user_id=user.id, server_id=server.id, kind="day2", sent=bool(ok)))
            session.commit()
            sent += int(bool(ok))
    return sent


def stats(session: Session, server: GameServer, days: int = 30) -> dict[str, Any]:
    since = utc_now() - timedelta(days=days)
    acts = session.execute(select(PlayerServerActivity.first_seen_at, PlayerServerActivity.last_seen_at).where(
        PlayerServerActivity.server_id == server.id, PlayerServerActivity.first_seen_at >= since)).all()
    newcomers = len(acts)
    returned = sum(1 for f, last in acts if _msk_day(last) > _msk_day(f))
    counts = {f"{k}_{s}": n for k, s, n in session.execute(
        select(RetentionDelivery.kind, RetentionDelivery.status, func.count()).where(
            RetentionDelivery.server_id == server.id, RetentionDelivery.created_at >= since)
        .group_by(RetentionDelivery.kind, RetentionDelivery.status)).all()}
    reminders = session.scalar(select(func.count()).select_from(PlayerReminder).where(
        PlayerReminder.server_id == server.id, PlayerReminder.kind == "day2", PlayerReminder.sent.is_(True),
        PlayerReminder.created_at >= since)) or 0
    recent = session.scalars(select(RetentionDelivery).where(RetentionDelivery.server_id == server.id)
                             .order_by(RetentionDelivery.created_at.desc()).limit(25)).all()
    return {
        "days": days, "newcomers": newcomers, "returned": returned,
        "returned_pct": round(returned * 100 / newcomers, 1) if newcomers else None,
        "deliveries": counts, "reminders_sent": int(reminders),
        "recent": [{"id": r.id, "nickname": r.nickname, "kind": r.kind, "status": r.status, "attempts": r.attempts,
                    "created_at": r.created_at.isoformat(), "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
                    "last_error": r.last_error, "created_by": r.created_by} for r in recent],
    }
