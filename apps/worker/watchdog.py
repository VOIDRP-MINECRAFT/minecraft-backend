"""The per-server watchdog: notices a server that is down or has stopped answering, and
restarts a hung one — for every server in the admin panel's list that has a systemd unit
and RCON, today's and any added later. Switched on per server (Мониторинг → Присмотр за
сервером → Сторож зависаний), thresholds in the same card; a server marked as watched by
a script of its own (the main one) is left to it.

Run from cron every minute::

    * * * * * cd /home/mironoouv/minecraft/minecraft_backend && .venv/bin/python -m apps.worker.watchdog >> /home/mironoouv/logs/watchdog-worker.log 2>&1

Each run looks at every server whose switch is on:

- its systemd unit not running → a "down" event, once (Restart=always normally brings it
  back by itself; if it stays down, that is for a person);
- just started → left alone for ``startup_grace_minutes`` to boot;
- otherwise asked over RCON (``list``). No answer for ``hang_minutes`` → hung: a thread
  dump is saved next to its logs (``jcmd Thread.print`` — what it was stuck on), and with
  ``action: restart`` the JVM is killed; systemd starts it again within 15 s. The JVM runs
  under the same user as this worker, so no sudo is needed.

It stays away from a server with ``maintenance.flag`` in its folder, one being restored
from a backup, and one it has already restarted ``max_restarts_per_hour`` times in the
last hour — a server that hangs again straight away needs a person, not a loop.
"""
from __future__ import annotations

import fcntl
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.db import SessionLocal
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_backup import ServerBackupRestore
from apps.api.app.models.server_watchdog import ServerWatchdog, ServerWatchdogEvent, default_watchdog

log = logging.getLogger("watchdog-worker")
LOCK = "/tmp/voidrp-watchdog-worker.lock"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def unit(server: GameServer) -> dict[str, str]:
    return server_ops._systemctl_props(
        server.systemd_unit, ("ActiveState", "SubState", "MainPID", "ExecMainStartTimestampMonotonic")
    )


def uptime_seconds(pid: int) -> float | None:
    try:
        return max(0.0, now().timestamp() - psutil.Process(pid).create_time())
    except psutil.Error:
        return None


def event(session: Session, server: GameServer, kind: str, detail: str, dump: str | None = None) -> None:
    session.add(ServerWatchdogEvent(server_id=server.id, kind=kind, detail=detail[:4000], dump_path=dump))
    log.info("%s: %s — %s", server.slug, kind, detail)


def thread_dump(server: GameServer, pid: int, data_dir: str | None) -> tuple[str | None, str]:
    """Saves ``jcmd Thread.print`` next to the server's logs. Returns (path, the main
    thread's first frames) — the frames go into the event, so the admin panel shows at a
    glance what the server was stuck on."""
    try:
        proc = psutil.Process(pid)
        jcmd = server_ops._jcmd_bin(proc)
    except psutil.Error:
        return None, ""
    if not jcmd:
        return None, ""
    try:
        res = subprocess.run([jcmd, str(pid), "Thread.print"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"(дамп не снят: {exc})"
    out = res.stdout or ""
    if not out.strip():
        return None, "(дамп пуст)"
    folder = Path(data_dir or "/tmp") / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"watchdog-dump-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(out)
    main = ""
    blocks = out.split("\n\n")
    for block in blocks:
        if block.startswith('"Server thread"'):
            frames = [ln.strip() for ln in block.splitlines()[1:] if ln.strip().startswith(("at ", "java.lang.Thread.State"))]
            main = "\n".join(frames[:12])
            break
    return str(path), main


def check(session: Session, server: GameServer, wd: ServerWatchdog) -> None:
    cfg = {**default_watchdog(), **(wd.config or {})}
    state = dict(wd.state or {})
    t = now()
    state["checked_at"] = iso(t)

    def settle(status: str) -> None:
        state["status"] = status
        wd.state = state

    if not server.systemd_unit:
        settle("not_configured")
        return
    data_dir = server_ops.resolve_data_dir(server)
    if data_dir and (Path(data_dir) / "maintenance.flag").exists():
        state.pop("failing_since", None)
        settle("maintenance")
        return
    if session.query(ServerBackupRestore).filter(
        ServerBackupRestore.server_id == server.id, ServerBackupRestore.status.in_(("pending", "running"))
    ).first() is not None:
        state.pop("failing_since", None)
        settle("restoring")
        return

    props = unit(server)
    active, sub, pid = props.get("ActiveState", ""), props.get("SubState", ""), int(props.get("MainPID") or 0)
    if active != "active" or pid <= 0:
        # activating/auto-restart is systemd bringing it back — a moment, not an outage.
        if active == "activating":
            settle("booting")
            return
        if state.get("status") != "down":
            event(session, server, "down", f"Юнит {server.systemd_unit} не запущен: {active}/{sub}. "
                                           "systemd поднимает его сам (Restart=always); если он так и стоит — нужен человек.")
        state.pop("failing_since", None)
        settle("down")
        return

    up = uptime_seconds(pid) or 0
    try:
        server_ops.rcon_command(server, "list", timeout=10)
        answered = True
    except Exception as exc:  # noqa: BLE001 — any failure to answer is what we watch for
        answered = False
        state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]

    if answered:
        if state.get("restarted_at"):
            took = (t - parse(state.pop("restarted_at"))).total_seconds()
            event(session, server, "recovered", f"Поднялся после перезапуска за {int(took // 60)} мин {int(took % 60)} с и отвечает.")
        elif state.get("status") in ("unresponsive", "down") and state.get("failing_since"):
            since = parse(state["failing_since"])
            event(session, server, "recovered", f"Снова отвечает (молчал {int((t - since).total_seconds() // 60)} мин).")
        state.pop("failing_since", None)
        state["answered_at"] = iso(t)
        settle("ok")
        return

    if up < cfg["startup_grace_minutes"] * 60:
        settle("booting")
        return

    since = parse(state.get("failing_since")) or t
    state["failing_since"] = iso(since)
    silent = (t - since).total_seconds() / 60
    if silent < cfg["hang_minutes"]:
        settle("unresponsive")
        return

    # Hung. What was it doing?
    dump, main = thread_dump(server, pid, data_dir)
    stuck = f"Не отвечает {int(silent)} мин (RCON: {state.get('last_error', '—')})."
    if main:
        stuck += f"\nГлавный поток:\n{main}"

    if cfg["action"] != "restart":
        if not state.get("reported_hang"):
            event(session, server, "hang", stuck + "\nПерезапуск выключен в настройках — нужен человек.", dump)
            state["reported_hang"] = True
        settle("unresponsive")
        return

    hour_ago = t - timedelta(hours=1)
    recent = session.query(ServerWatchdogEvent).filter(
        ServerWatchdogEvent.server_id == server.id, ServerWatchdogEvent.kind == "restart",
        ServerWatchdogEvent.created_at >= hour_ago,
    ).count()
    if recent >= cfg["max_restarts_per_hour"]:
        if not state.get("reported_limit"):
            event(session, server, "limit", stuck + f"\nЗа час уже {recent} перезапуска — дальше не перезапускаю, нужен человек.", dump)
            state["reported_limit"] = True
        settle("unresponsive")
        return

    try:
        proc = psutil.Process(pid)
        if proc.uids().real != os.getuid():
            raise PermissionError("процесс сервера запущен под другим пользователем")
        os.kill(pid, signal.SIGKILL)
        event(session, server, "restart", stuck + "\nПроцесс остановлен, systemd запускает сервер заново.", dump)
        state["restarted_at"] = iso(t)
    except Exception as exc:  # noqa: BLE001
        event(session, server, "hang", stuck + f"\nПерезапустить не удалось: {exc}", dump)
    state.pop("failing_since", None)
    state.pop("reported_hang", None)
    state.pop("reported_limit", None)
    settle("restarted")


def switched_on(server: GameServer, wd: ServerWatchdog | None) -> bool:
    """The Monitoring card's "Сторож зависаний" switch (a file in the server's folder) —
    unless the server is set as watched by a script of its own."""
    if not server.systemd_unit or (wd is not None and (wd.config or {}).get("own_script")):
        return False
    state = server_ops.get_watchdog_state(server)
    return bool(state.get("available") and state.get("enabled"))


def run(session: Session) -> None:
    rows = {w.server_id: w for w in session.query(ServerWatchdog).all()}
    for server in session.query(GameServer).all():
        wd = rows.get(server.id)
        if not switched_on(server, wd):
            if wd is not None and (wd.state or {}).get("status") != "off":
                wd.state = {**(wd.state or {}), "status": "off"}
            continue
        if wd is None:
            wd = ServerWatchdog(server_id=server.id, config=default_watchdog(), state={})
            session.add(wd)
        try:
            check(session, server, wd)
        except Exception as exc:  # noqa: BLE001 — one server's trouble must not stop the rest
            log.exception("%s: watchdog check failed: %s", server.slug, exc)
        session.commit()
    session.commit()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    session = SessionLocal()
    try:
        run(session)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
