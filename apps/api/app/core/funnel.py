"""Newcomer funnel: where players drop between signing up and playing for a week.

Steps per account (staff excluded), from data the platform already has:

1. registered          — ``users.created_at``;
2. launched            — got a play ticket from the launcher (``play_tickets``) or showed up
                         on a server from another client (``player_server_activity``);
3. joined              — actually entered a server: a ticket was consumed, or a server saw them;
4. returned            — active on a second calendar day (ticket or playtime);
5. week                — active again 7+ days after the first day.

Plus a side number: 15+ minutes in game (``player_playtime_daily`` exists only since 09.09, so
it is counted among those who got in and signed up after that, outside the chain).

Cohorts by registration week; filters by server and by source (site / in game / referral).
"Stuck" lists name the people worth a message: registered but never launched, launched but
never got in, played one day and vanished.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.play_ticket import PlayTicket
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_activity import PlayerServerActivity
from apps.api.app.models.player_playtime_daily import PlayerPlaytimeDaily
from apps.api.app.models.referral_link import ReferralLink
from apps.api.app.models.user import User

# A chain: each step counts only those who passed the previous one, so the funnel never grows.
STEPS = [
    ("registered", "Зарегистрировались"),
    ("launched", "Запустили игру"),
    ("joined", "Зашли на сервер"),
    ("returned", "Вернулись на другой день"),
    ("week", "Играют через неделю"),
]
PLAYTIME_SINCE = date(2026, 9, 9)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build(session: Session, *, server_id: UUID | None = None, source: str | None = None, weeks: int = 12) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(weeks=weeks)

    users = session.execute(
        select(User.id, User.site_login, User.email, User.created_at, User.telegram_user_id,
               PlayerAccount.minecraft_nickname, PlayerAccount.registration_source, PlayerAccount.registration_server_id)
        .join(PlayerAccount, PlayerAccount.user_id == User.id, isouter=True)
        .where(User.is_admin.is_(False), User.is_moderator.is_(False), User.created_at >= since)
    ).all()
    referred = {u for (u,) in session.execute(select(ReferralLink.invited_user_id)).all()}

    def source_of(row) -> str:
        if row.id in referred:
            return "referral"
        return "game" if row.registration_source == "game" else "site"

    people = [u for u in users if not source or source_of(u) == source]
    ids = [u.id for u in people]
    if not ids:
        return {"steps": [{"key": k, "label": label, "count": 0} for k, label in STEPS], "cohorts": [], "stuck": {},
                "total": 0, "playtime_since": PLAYTIME_SINCE.isoformat(), "sources": {}}

    # Activity days per user: tickets issued, server presence, playtime.
    days: dict[UUID, set[date]] = defaultdict(set)
    launched: set[UUID] = set()
    joined: set[UUID] = set()
    last_seen: dict[UUID, datetime] = {}

    q = select(PlayTicket.user_id, PlayTicket.issued_at, PlayTicket.consumed_at).where(PlayTicket.user_id.in_(ids))
    if server_id:
        q = q.where(PlayTicket.server_id == server_id)
    for uid, issued, consumed in session.execute(q).all():
        launched.add(uid)
        days[uid].add(issued.date())
        if consumed:
            joined.add(uid)
        last_seen[uid] = max(last_seen.get(uid, issued), issued)

    q = select(PlayerServerActivity.user_id, PlayerServerActivity.first_seen_at, PlayerServerActivity.last_seen_at).where(
        PlayerServerActivity.user_id.in_(ids))
    if server_id:
        q = q.where(PlayerServerActivity.server_id == server_id)
    for uid, first, last in session.execute(q).all():
        launched.add(uid)
        joined.add(uid)
        days[uid].add(first.date())
        days[uid].add(last.date())
        last_seen[uid] = max(last_seen.get(uid, last), last)

    nick_to_user = {(u.minecraft_nickname or "").lower(): u.id for u in people if u.minecraft_nickname}
    playtime: dict[UUID, int] = defaultdict(int)
    q = select(PlayerPlaytimeDaily.minecraft_nickname_normalized, PlayerPlaytimeDaily.day, PlayerPlaytimeDaily.seconds).where(
        PlayerPlaytimeDaily.minecraft_nickname_normalized.in_(list(nick_to_user)))
    if server_id:
        q = q.where(PlayerPlaytimeDaily.server_id == server_id)
    for nick, day, secs in session.execute(q).all():
        uid = nick_to_user.get(nick)
        if uid:
            playtime[uid] += int(secs or 0)
            if secs:
                days[uid].add(day)

    def steps_of(u) -> dict[str, bool]:
        d = sorted(days.get(u.id, ()))
        first = d[0] if d else None
        f = {
            "registered": True,
            "launched": u.id in launched,
            "joined": u.id in joined,
            "returned": len(d) >= 2,
            "week": bool(first and d[-1] >= first + timedelta(days=7)),
        }
        ok = True
        for k, _ in STEPS:
            ok = ok and f[k]
            f[k] = ok
        f["played15"] = playtime.get(u.id, 0) >= 900
        return f

    flags = {u.id: steps_of(u) for u in people}
    counts = {k: sum(1 for f in flags.values() if f[k]) for k, _ in STEPS}
    steps = []
    prev = None
    for k, label in STEPS:
        n = counts[k]
        steps.append({"key": k, "label": label, "count": n,
                      "of_prev": round(n * 100 / prev, 1) if prev else None,
                      "of_first": round(n * 100 / counts["registered"], 1) if counts["registered"] else None,
                      "lost": (prev - n) if prev is not None else None})
        prev = n

    by_week: dict[date, list] = defaultdict(list)
    for u in people:
        by_week[_week_start(u.created_at.date())].append(flags[u.id])
    cohorts = []
    for wk in sorted(by_week, reverse=True):
        rows = by_week[wk]
        cohorts.append({"start": wk.isoformat(), "mature": (now.date() - wk).days >= 14,
                        **{k: sum(1 for f in rows if f[k]) for k, _ in STEPS}})

    def person(u) -> dict[str, Any]:
        return {"login": u.site_login, "nickname": u.minecraft_nickname, "email": u.email, "telegram": bool(u.telegram_user_id),
                "registered_at": u.created_at.isoformat(), "source": source_of(u),
                "last_seen_at": last_seen[u.id].isoformat() if u.id in last_seen else None,
                "playtime_min": round(playtime.get(u.id, 0) / 60)}

    three_days_ago = now - timedelta(days=3)
    stuck = {
        "no_launch": [person(u) for u in people if not flags[u.id]["launched"] and u.created_at < now - timedelta(hours=6)],
        "no_join": [person(u) for u in people if flags[u.id]["launched"] and not flags[u.id]["joined"]],
        "one_day": [person(u) for u in people if flags[u.id]["joined"] and not flags[u.id]["returned"]
                    and last_seen.get(u.id, now) < three_days_ago],
    }
    for k in stuck:
        stuck[k].sort(key=lambda p: p["registered_at"], reverse=True)
        stuck[k] = stuck[k][:50]

    # 15+ minutes: a side number — playtime exists only since PLAYTIME_SINCE, so count among those
    # who got in and signed up after it.
    recent_joined = [u for u in people if flags[u.id]["joined"] and u.created_at.date() >= PLAYTIME_SINCE]
    played15 = {"joined": len(recent_joined), "played15": sum(1 for u in recent_joined if flags[u.id]["played15"])}

    src_counts: dict[str, int] = defaultdict(int)
    for u in users:
        src_counts[source_of(u)] += 1
    return {"steps": steps, "cohorts": cohorts, "stuck": stuck, "total": len(people),
            "playtime_since": PLAYTIME_SINCE.isoformat(), "sources": dict(src_counts), "weeks": weeks,
            "played15": played15}
