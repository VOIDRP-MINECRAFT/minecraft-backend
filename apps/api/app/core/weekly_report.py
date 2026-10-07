"""The week of our own servers in one Telegram message: for the platform's admins.

Sent on Mondays with the partners' digest (apps/worker/integration_digest.py) for the past
Moscow week (Mon–Sun), and on demand by the bot's ``/week`` (the last 7 days). Each number is
compared with the 7 days before. Staff are left out of every player count.

Per server (``is_external`` false): players and hours in game, newcomers and how many came
back on another day, peak online and TPS (where monitoring samples exist), incidents and
downtime, monitoring votes, «Возврат игроков» rewards delivered. Platform-wide: sign-ups and
where they came from. Ends with what deserves a look, by simple rules.
"""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_activity import PlayerServerActivity
from apps.api.app.models.player_playtime_daily import PlayerPlaytimeDaily
from apps.api.app.models.referral_link import ReferralLink
from apps.api.app.models.retention import MonitoringVote, PlayerLoginDay, RetentionDelivery
from apps.api.app.models.server_incident import ServerIncident
from apps.api.app.models.server_status_sample import ServerStatusSample
from apps.api.app.models.user import User

MSK = timezone(timedelta(hours=3))
_MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_SOURCES = {"site": "сайт", "game": "в игре", "referral": "приглашения", "staff": "от команды"}


def last_full_week(now: datetime | None = None) -> date:
    """Monday of the Moscow week that ended most recently."""
    today = (now or datetime.now(timezone.utc)).astimezone(MSK).date()
    return today - timedelta(days=today.weekday() + 7)


def _bounds(first: date) -> tuple[datetime, datetime]:
    start = datetime.combine(first, time(), MSK)
    return start, start + timedelta(days=7)


def _staff(session: Session) -> tuple[set, set[str]]:
    rows = session.execute(select(User.id, PlayerAccount.minecraft_nickname_normalized)
                           .join(PlayerAccount, PlayerAccount.user_id == User.id, isouter=True)
                           .where((User.is_admin.is_(True)) | (User.is_moderator.is_(True)))).all()
    return {r[0] for r in rows}, {r[1] for r in rows if r[1]}


def _server_week(session: Session, server: GameServer, first: date, staff_ids: set, staff_nicks: set[str]) -> dict[str, Any]:
    start, end = _bounds(first)
    last = first + timedelta(days=6)
    sid = server.id

    nick_of = dict(session.execute(select(PlayerAccount.user_id, PlayerAccount.minecraft_nickname_normalized)).all())
    days: dict[str, set[date]] = defaultdict(set)   # nickname → active days (any time, for "came back")
    seconds = 0
    for nick, day, secs in session.execute(select(PlayerPlaytimeDaily.minecraft_nickname_normalized, PlayerPlaytimeDaily.day,
                                                  PlayerPlaytimeDaily.seconds)
                                           .where(PlayerPlaytimeDaily.server_id == sid, PlayerPlaytimeDaily.day >= first)).all():
        if nick in staff_nicks or not secs:
            continue
        days[nick].add(day)
        if day <= last:
            seconds += int(secs)
    for uid, day in session.execute(select(PlayerLoginDay.user_id, PlayerLoginDay.day)
                                    .where(PlayerLoginDay.server_id == sid, PlayerLoginDay.day >= first)).all():
        nick = nick_of.get(uid)
        if nick and uid not in staff_ids:
            days[nick].add(day)
    active = {n for n, d in days.items() if any(first <= x <= last for x in d)}
    # Presence covers the days before playtime / login days were kept on a server.
    for uid in session.scalars(select(PlayerServerActivity.user_id).where(
            PlayerServerActivity.server_id == sid, PlayerServerActivity.last_seen_at >= start,
            PlayerServerActivity.first_seen_at < end)).all():
        if uid not in staff_ids and nick_of.get(uid):
            active.add(nick_of[uid])
    players = len(active)

    newcomers = [(uid, seen) for uid, seen in session.execute(
        select(PlayerServerActivity.user_id, PlayerServerActivity.first_seen_at)
        .where(PlayerServerActivity.server_id == sid, PlayerServerActivity.first_seen_at >= start,
               PlayerServerActivity.first_seen_at < end)).all() if uid not in staff_ids]
    returned = 0
    for uid, seen in newcomers:
        d0 = seen.astimezone(MSK).date()
        if any(x > d0 for x in days.get(nick_of.get(uid) or "", ())):
            returned += 1

    peak, tps = session.execute(select(func.max(ServerStatusSample.online), func.avg(ServerStatusSample.tps))
                                .where(ServerStatusSample.server_id == sid, ServerStatusSample.at >= start,
                                       ServerStatusSample.at < end)).one()

    incidents = session.execute(select(ServerIncident.kind, ServerIncident.started_at, ServerIncident.ended_at)
                                .where(ServerIncident.server_id == sid, ServerIncident.started_at < end,
                                       (ServerIncident.ended_at.is_(None)) | (ServerIncident.ended_at >= start))).all()
    now = datetime.now(timezone.utc)
    down_min = sum(((min(e or now, end) - max(s, start)).total_seconds() / 60) for k, s, e in incidents if k == "down")

    votes = session.scalar(select(func.count()).select_from(MonitoringVote)
                           .where(MonitoringVote.server_id == sid, MonitoringVote.vote_day >= first,
                                  MonitoringVote.vote_day <= last)) or 0
    rewards = dict(session.execute(select(RetentionDelivery.kind, func.count())
                                   .where(RetentionDelivery.server_id == sid, RetentionDelivery.status == "delivered",
                                          RetentionDelivery.delivered_at >= start, RetentionDelivery.delivered_at < end)
                                   .group_by(RetentionDelivery.kind)).all())
    return {"players": players, "hours": round(seconds / 3600, 1), "newcomers": len(newcomers), "returned": returned,
            "peak": peak, "tps": round(float(tps), 1) if tps is not None else None,
            "incidents": len(incidents), "down_min": round(down_min), "votes": votes, "rewards": rewards}


def _signups(session: Session, first: date) -> dict[str, Any]:
    start, end = _bounds(first)
    referred = {u for (u,) in session.execute(select(ReferralLink.invited_user_id)).all()}
    rows = session.execute(select(User.id, User.signup_source, PlayerAccount.registration_source)
                           .join(PlayerAccount, PlayerAccount.user_id == User.id, isouter=True)
                           .where(User.is_admin.is_(False), User.is_moderator.is_(False),
                                  User.created_at >= start, User.created_at < end)).all()
    by: dict[str, int] = defaultdict(int)
    for uid, label, reg in rows:
        by["referral" if uid in referred else label or ("game" if reg == "game" else "site")] += 1
    return {"total": len(rows), "sources": dict(sorted(by.items(), key=lambda kv: -kv[1]))}


def build(session: Session, first: date) -> dict[str, Any]:
    """The week starting on ``first`` (a Moscow date) and the one before it."""
    staff_ids, staff_nicks = _staff(session)
    prev = first - timedelta(days=7)
    servers = session.scalars(select(GameServer).where(GameServer.is_external.is_(False))
                              .order_by(GameServer.sort_order, GameServer.name)).all()
    out = []
    for s in servers:
        now_w = _server_week(session, s, first, staff_ids, staff_nicks)
        if not (now_w["players"] or now_w["newcomers"] or now_w["peak"]):
            continue
        out.append({"server": s, "now": now_w, "prev": _server_week(session, s, prev, staff_ids, staff_nicks)})
    return {"first": first, "servers": out, "signups": _signups(session, first), "signups_prev": _signups(session, prev)}


# ── the message ──────────────────────────────────────────────────────────────

def _delta(now: float | None, prev: float | None, unit: str = "") -> str:
    if now is None:
        return "—"
    shown = f"{now:g}{unit}"
    if prev is None:
        return shown
    d = round(now - prev, 1)
    if d == 0:
        return f"{shown} (=)"
    return f"{shown} ({'▲' if d > 0 else '▼'}{abs(d):g})"


def _day(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]}"


def text(report: dict[str, Any], *, rolling: bool = False) -> str:
    first: date = report["first"]
    head = "последние 7 дней" if rolling else f"{_day(first)} – {_day(first + timedelta(days=6))}"
    lines = [f"📊 <b>Неделя VoidRP</b> · {head}", ""]
    watch: list[str] = []
    for row in report["servers"]:
        s, n, p = row["server"], row["now"], row["prev"]
        lines.append(f"<b>{html.escape(s.name)}</b>")
        hours = f" · часов в игре: {_delta(n['hours'], p['hours'])}" if n["hours"] or p["hours"] else ""
        lines.append(f"👥 Игроков: {_delta(n['players'], p['players'])}{hours}")
        if n["newcomers"]:
            share = round(n["returned"] * 100 / n["newcomers"])
            lines.append(f"🌱 Новичков: {_delta(n['newcomers'], p['newcomers'])} · вернулись на другой день: {n['returned']} ({share}%)")
            if n["newcomers"] >= 4 and share < 40:
                watch.append(f"{s.name}: из {n['newcomers']} новичков вернулись только {n['returned']}")
        else:
            lines.append("🌱 Новичков не было")
        if n["peak"] is not None:
            lines.append(f"📈 Пик онлайна: {_delta(n['peak'], p['peak'])}" + (f" · TPS в среднем {n['tps']:g}" if n["tps"] is not None else ""))
            if n["tps"] is not None and n["tps"] < 18:
                watch.append(f"{s.name}: средний TPS {n['tps']:g}")
        if n["incidents"]:
            lines.append(f"🚨 Инцидентов: {n['incidents']}" + (f", лежал {n['down_min']} мин" if n["down_min"] else ""))
            if n["down_min"] >= 30:
                watch.append(f"{s.name}: простой {n['down_min']} мин")
        extra = []
        if n["votes"] or p["votes"]:
            extra.append(f"голосов {_delta(n['votes'], p['votes'])}")
        given = sum(n["rewards"].values())
        if given:
            extra.append(f"наград «Возврата» {given}")
        if extra:
            lines.append("🎁 " + " · ".join(extra))
        if p["players"] and n["players"] <= p["players"] * 0.7:
            watch.append(f"{s.name}: игроков меньше на {p['players'] - n['players']}")
        lines.append("")
    su, sp = report["signups"], report["signups_prev"]
    src = ", ".join(f"{_SOURCES.get(k, k)} {v}" for k, v in list(su["sources"].items())[:4])
    lines.append(f"📝 Регистраций: {_delta(su['total'], sp['total'])}" + (f" — {html.escape(src)}" if src else ""))
    if not report["servers"]:
        lines.insert(2, "За неделю на наших серверах никого не было.")
    if watch:
        lines += ["", "👀 <b>Стоит посмотреть</b>"] + [f"• {html.escape(w)}" for w in watch]
    return "\n".join(lines).strip()


def rolling_first(now: datetime | None = None) -> date:
    """First day of «the last 7 days» (today included), for /week."""
    return (now or datetime.now(timezone.utc)).astimezone(MSK).date() - timedelta(days=6)
