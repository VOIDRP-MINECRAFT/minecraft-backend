"""A game server over time: five-minute snapshots, uptime, the players/TPS chart.

Snapshots come from the monitoring heartbeat (VoidRpPerms, VoidRpGameSync…) at most every
``EVERY``; when a server that has reported before goes silent, ``integration_watch`` writes a
"down" snapshot instead, so uptime counts the outage. Kept ``KEEP_DAYS`` days.

Uptime is the share of snapshots that were up, so a backend outage (no snapshots at all) does
not count against a server.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.api.app.core import server_reports
from apps.api.app.core.security import utc_now
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_report import ServerPluginReport
from apps.api.app.models.server_status_sample import ServerStatusSample
from apps.api.app.services.redis_cache_service import RedisCacheService

EVERY = timedelta(minutes=5)
KEEP_DAYS = 35


def _due(server: GameServer) -> bool:
    """At most one snapshot per EVERY per server (Redis, so several workers agree)."""
    cache = RedisCacheService()
    key = f"status_sample_at:{server.id}"
    last = cache.get_json(key)
    now = utc_now()
    if last and now - datetime.fromisoformat(last["at"]) < EVERY:
        return False
    cache.set_json(key, {"at": now.isoformat()}, ttl_seconds=int(EVERY.total_seconds() * 3))
    return True


def is_up(session: Session, server: GameServer) -> bool:
    """A partner's server is up when its required modules answer; ours when anything does."""
    if server.is_external:
        return not server_reports.missing_required(session, server)
    return any(server_reports.is_fresh(r) for r in server_reports.reports(session, server))


def record_heartbeat(session: Session, server: GameServer, report: ServerPluginReport) -> None:
    """From a heartbeat carrying monitoring numbers. Commits nothing."""
    data = report.data or {}
    if "online" not in data or not _due(server):
        return
    session.add(ServerStatusSample(
        server_id=server.id, up=is_up(session, server), online=data.get("online"),
        max_players=data.get("max"), tps=data.get("tps"), mspt=data.get("mspt"),
    ))


def record_silence(session: Session) -> int:
    """Down snapshots for servers that reported before and are silent now (cron)."""
    written = 0
    for server in session.scalars(select(GameServer)).all():
        reports = server_reports.reports(session, server)
        if not reports or any(server_reports.is_fresh(r) for r in reports):
            continue
        if server.maintenance:
            continue  # planned downtime is not an outage
        if _due(server):
            session.add(ServerStatusSample(server_id=server.id, up=False))
            written += 1
    if written:
        session.commit()
    return written


def trim(session: Session) -> None:
    cache = RedisCacheService()
    if cache.get_json("status_samples_trimmed"):
        return
    cache.set_json("status_samples_trimmed", {"at": utc_now().isoformat()}, ttl_seconds=3600)
    session.execute(delete(ServerStatusSample).where(ServerStatusSample.at < utc_now() - timedelta(days=KEEP_DAYS)))
    session.commit()


def _uptime(session: Session, server: GameServer, since: datetime) -> float | None:
    total, up = session.execute(
        select(func.count(), func.count().filter(ServerStatusSample.up.is_(True)))
        .where(ServerStatusSample.server_id == server.id, ServerStatusSample.at >= since)
    ).one()
    return round(up * 100.0 / total, 2) if total else None


def summary(session: Session, server: GameServer) -> dict[str, Any]:
    """Uptime for 24 h / 7 / 30 days, the last day in 15-minute points, 30 daily bars."""
    now = utc_now()
    day_ago = now - timedelta(hours=24)
    rows = session.execute(
        select(ServerStatusSample.at, ServerStatusSample.up, ServerStatusSample.online, ServerStatusSample.tps)
        .where(ServerStatusSample.server_id == server.id, ServerStatusSample.at >= day_ago)
        .order_by(ServerStatusSample.at)
    ).all()
    buckets: dict[int, list] = {}
    for at, up, online, tps in rows:
        buckets.setdefault(int((at - day_ago).total_seconds() // 900), []).append((up, online, tps))
    series = []
    for i in range(96):
        b = buckets.get(i)
        t = (day_ago + timedelta(minutes=15 * i)).isoformat()
        if not b:
            series.append({"t": t, "up": None, "online": None, "tps": None})
            continue
        onl = [o for _, o, _ in b if o is not None]
        tps = [x for _, _, x in b if x is not None]
        series.append({"t": t, "up": sum(1 for u, _, _ in b if u) / len(b),
                       "online": round(sum(onl) / len(onl), 1) if onl else None,
                       "tps": round(sum(tps) / len(tps), 2) if tps else None})

    month_ago = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    day = func.date_trunc("day", ServerStatusSample.at)
    daily = {d.date(): (total, up) for d, total, up in session.execute(
        select(day, func.count(), func.count().filter(ServerStatusSample.up.is_(True)))
        .where(ServerStatusSample.server_id == server.id, ServerStatusSample.at >= month_ago)
        .group_by(day)
    ).all()}
    bars = []
    for i in range(30):
        d = (month_ago + timedelta(days=i)).date()
        total, up = daily.get(d, (0, 0))
        bars.append({"day": d.isoformat(), "uptime": round(up * 100.0 / total, 1) if total else None})

    peak = max((o for _, _, o, _ in rows if o is not None), default=None)
    return {
        "uptime_24h": _uptime(session, server, day_ago),
        "uptime_7d": _uptime(session, server, now - timedelta(days=7)),
        "uptime_30d": _uptime(session, server, now - timedelta(days=30)),
        "peak_24h": peak,
        "series_24h": series,
        "bars_30d": bars,
        "samples_since": session.scalar(select(func.min(ServerStatusSample.at)).where(
            ServerStatusSample.server_id == server.id)),
    }


# ── Incidents ─────────────────────────────────────────────────────────────────
TPS_LOW = 15.0
TPS_OK = 17.0
TPS_SAMPLES = 2          # two five-minute snapshots in a row: ten minutes
DOWN_AFTER = timedelta(minutes=5)


def _open(session: Session, server: GameServer, kind: str):
    from apps.api.app.models.server_incident import ServerIncident

    return session.scalar(select(ServerIncident).where(
        ServerIncident.server_id == server.id, ServerIncident.kind == kind, ServerIncident.ended_at.is_(None)))


def detect_incidents(session: Session) -> list[tuple[str, GameServer, Any]]:
    """Opens and closes incidents (cron). Returns [(event, server, incident)] for the notices:
    event is "down", "up", "tps_low" or "tps_ok"."""
    from apps.api.app.models.server_incident import ServerIncident

    events: list[tuple[str, GameServer, Any]] = []
    now = utc_now()
    for server in session.scalars(select(GameServer)).all():
        reports = server_reports.reports(session, server)
        if not reports:
            continue
        last = max((r.reported_at for r in reports if r.reported_at), default=None)
        silent = last is not None and now - last > DOWN_AFTER
        missing = server_reports.missing_required(session, server) if server.is_external else []
        down = (silent or bool(missing)) and not server.maintenance
        inc = _open(session, server, "down")
        if down and inc is None:
            what = "сервер не отвечает" if silent else "не работают: " + "; ".join(missing)
            inc = ServerIncident(server_id=server.id, kind="down", started_at=last if silent and last else now,
                                 detail=what[:300])
            session.add(inc)
            session.flush()
            events.append(("down", server, inc))
        elif not down and inc is not None:
            inc.ended_at = now
            events.append(("up", server, inc))

        recent = session.scalars(select(ServerStatusSample).where(
            ServerStatusSample.server_id == server.id, ServerStatusSample.tps.is_not(None))
            .order_by(ServerStatusSample.at.desc()).limit(TPS_SAMPLES)).all()
        tinc = _open(session, server, "tps")
        if len(recent) == TPS_SAMPLES and all(s.tps < TPS_LOW for s in recent) and not silent and tinc is None:
            tinc = ServerIncident(server_id=server.id, kind="tps", started_at=recent[-1].at,
                                  detail=f"TPS {recent[0].tps:.1f} (ниже {TPS_LOW:.0f} больше 10 минут)")
            session.add(tinc)
            session.flush()
            events.append(("tps_low", server, tinc))
        elif tinc is not None and ((recent and recent[0].tps >= TPS_OK) or silent):
            tinc.ended_at = now
            events.append(("tps_ok", server, tinc))
    session.commit()
    return events


def incidents(session: Session, server: GameServer, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
    from apps.api.app.models.server_incident import ServerIncident

    rows = session.scalars(select(ServerIncident).where(
        ServerIncident.server_id == server.id, ServerIncident.started_at >= utc_now() - timedelta(days=days))
        .order_by(ServerIncident.started_at.desc()).limit(limit)).all()
    now = utc_now()
    return [{"id": r.id, "kind": r.kind, "started_at": r.started_at.isoformat(),
             "ended_at": r.ended_at.isoformat() if r.ended_at else None,
             "minutes": int(((r.ended_at or now) - r.started_at).total_seconds() // 60), "detail": r.detail}
            for r in rows]
