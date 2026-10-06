"""Votes for a server on monitoring sites (top lists): the site calls us when a player votes.

Every monitoring signs its callback its own way, so the check is configured per monitoring in
«Возврат игроков» (``retention_settings.votes.providers``): which request fields hold the
nickname, the time and the signature, the hash (md5 / sha1 / sha256) and the order of what is
hashed, e.g. ``{nick}{time}{secret}``. Copy those from the monitoring's own documentation —
the presets below are just the common shapes.

``GET|POST /votes/{server}/{provider}`` → checks the signature (and that the time is fresh when
it is a unix timestamp), records one vote per player, monitoring and Moscow day, and queues
the reward (kind ``vote``; owed until the player's next login if they are away).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.api.app.core.retention import MSK, NICK, settings
from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.retention import MonitoringVote, RetentionDelivery

PRESETS = {
    "sha1_nick_time_secret": {"label": "SHA1(ник + время + секрет)", "algo": "sha1", "formula": "{nick}{time}{secret}"},
    "md5_nick_time_secret": {"label": "MD5(ник + время + секрет)", "algo": "md5", "formula": "{nick}{time}{secret}"},
    "sha256_nick_time_secret": {"label": "SHA256(ник + время + секрет)", "algo": "sha256", "formula": "{nick}{time}{secret}"},
    "sha1_nick_secret_time": {"label": "SHA1(ник + секрет + время)", "algo": "sha1", "formula": "{nick}{secret}{time}"},
    "md5_nick_secret": {"label": "MD5(ник + секрет), без времени", "algo": "md5", "formula": "{nick}{secret}"},
}
ALGOS = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256}
KEY = re.compile(r"^[a-z0-9_-]{2,32}$")
FIELD = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


class VoteRejected(Exception):
    pass


def provider_defaults() -> dict[str, Any]:
    return {"key": "", "name": "", "secret": "", "nick_field": "nick", "time_field": "time", "sign_field": "sign",
            "algo": "sha1", "formula": "{nick}{time}{secret}", "ok_text": "ok", "max_skew_minutes": 60}


def validate_provider(p: dict[str, Any]) -> str | None:
    if not KEY.match(p.get("key") or ""):
        return "ключ мониторинга — латиница, цифры, «-», «_» (2–32)"
    if not (p.get("secret") or "").strip():
        return f"«{p['key']}»: нужен секрет из кабинета мониторинга"
    for f in ("nick_field", "sign_field"):
        if not FIELD.match(p.get(f) or ""):
            return f"«{p['key']}»: неверное имя поля {f}"
    if p.get("time_field") and not FIELD.match(p["time_field"]):
        return f"«{p['key']}»: неверное имя поля времени"
    if p.get("algo") not in ALGOS:
        return f"«{p['key']}»: алгоритм — md5, sha1 или sha256"
    if "{secret}" not in (p.get("formula") or ""):
        return f"«{p['key']}»: в формуле должен быть {{secret}}"
    return None


def _provider(server: GameServer, key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = settings(server)
    votes = cfg.get("votes") or {}
    for p in votes.get("providers") or []:
        if p.get("key") == key:
            return {**provider_defaults(), **p}, votes
    raise VoteRejected("unknown monitoring")


def check(p: dict[str, Any], params: dict[str, str]) -> str:
    """The nickname when the request is genuine, else VoteRejected."""
    nick = (params.get(p["nick_field"]) or "").strip()
    sign = (params.get(p["sign_field"]) or "").strip().lower()
    ts = (params.get(p["time_field"]) or "").strip() if p.get("time_field") else ""
    if not nick or not sign:
        raise VoteRejected("missing fields")
    raw = p["formula"].replace("{nick}", nick).replace("{time}", ts).replace("{secret}", p["secret"])
    want = ALGOS[p["algo"]](raw.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(want, sign):
        raise VoteRejected("bad signature")
    skew = int(p.get("max_skew_minutes") or 0)
    if skew and ts.isdigit():
        stamp = int(ts) / (1000 if len(ts) > 11 else 1)
        if abs(time.time() - stamp) > skew * 60:
            raise VoteRejected("stale vote")
    return nick


def handle(session: Session, server: GameServer, key: str, params: dict[str, str], ip: str | None) -> str:
    p, votes = _provider(server, key)
    nick = check(p, params)
    day = datetime.now(MSK).date()
    res = session.execute(pg_insert(MonitoringVote).values(server_id=server.id, provider=key, nickname=nick[:32], vote_day=day, ip=ip)
                          .on_conflict_do_nothing(index_elements=["server_id", "provider", "nickname", "vote_day"]).returning(MonitoringVote.id))
    vote_id = res.scalar()
    if vote_id is None:  # the monitoring re-sent today's vote
        session.commit()
        return p["ok_text"]
    account = session.scalar(select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == nick.lower()))
    if account is not None:
        session.execute(MonitoringVote.__table__.update().where(MonitoringVote.id == vote_id).values(user_id=account.user_id))
    if votes.get("enabled") and votes.get("commands") and NICK.match(nick):
        session.add(RetentionDelivery(server_id=server.id, user_id=account.user_id if account else None,
                                      nickname=account.minecraft_nickname if account else nick, kind="vote",
                                      deliver_after=utc_now(), created_by=f"vote:{key}"))
        session.execute(MonitoringVote.__table__.update().where(MonitoringVote.id == vote_id).values(rewarded=True))
    session.commit()
    return p["ok_text"]


def stats(session: Session, server: GameServer, days: int = 30) -> list[dict[str, Any]]:
    from datetime import timedelta

    since = datetime.now(MSK).date() - timedelta(days=days)
    rows = session.execute(select(MonitoringVote.provider, func.count(), func.count(func.distinct(MonitoringVote.nickname)))
                           .where(MonitoringVote.server_id == server.id, MonitoringVote.vote_day >= since)
                           .group_by(MonitoringVote.provider)).all()
    return [{"provider": p, "votes": n, "players": u} for p, n, u in rows]
