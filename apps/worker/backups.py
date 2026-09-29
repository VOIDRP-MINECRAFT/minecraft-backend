"""The backup worker: does what the admin panel's Backups page queues.

Run from cron every minute::

    * * * * * cd /home/mironoouv/minecraft/minecraft_backend && .venv/bin/python -m apps.worker.backups >> /home/mironoouv/logs/backup-worker.log 2>&1

One at a time (a file lock; a run that finds another still going leaves at once). Each
run does, in order: restores asked for, backups asked for, backups the schedule is due
for, and pruning scheduled backups past the number to keep.

**A backup** of a running server: ``save-off`` so nothing is written mid-archive,
``save-all flush`` (RCON answers once the world is on disk), the world folders into a
``.tar.zst`` on the backup disk, ``save-on`` again whatever happened. Checked with
``zstd -t`` before it counts.

**A restore**: a backup first ("before restore"), so the restore can itself be undone;
the archive unpacked next to the server; players warned; ``stop`` over RCON; and in the
15 s before systemd starts the server again (``Restart=always``), the world folders
swapped for the unpacked ones — a rename on the same disk, instant. The server comes
back up on the restored world. No sudo anywhere: stopping is RCON, starting is systemd's.
"""
from __future__ import annotations

import fcntl
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.db import SessionLocal
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_backup import (
    ServerBackup,
    ServerBackupRestore,
    ServerBackupSettings,
    default_backup_settings,
)
from apps.api.app.services import backups as svc

log = logging.getLogger("backup-worker")

LOCK = "/tmp/voidrp-backup-worker.lock"
STAGING = ".voidrp-restore-"
OLD = ".voidrp-replaced-"


class Failed(Exception):
    """A step failed; the message is what the admin panel shows."""


def now() -> datetime:
    return datetime.now(timezone.utc)


# ── The server process ────────────────────────────────────────────────────────

def unit_state(server: GameServer) -> tuple[str, str, int]:
    """(ActiveState, SubState, MainPID) of the server's systemd unit."""
    props = server_ops._systemctl_props(server.systemd_unit, ("ActiveState", "SubState", "MainPID"))
    return props.get("ActiveState", ""), props.get("SubState", ""), int(props.get("MainPID") or 0)


def running(server: GameServer) -> bool:
    state, _sub, pid = unit_state(server)
    return state == "active" and pid > 0


def rcon(server: GameServer, command: str, timeout: float = 10.0) -> str:
    return server_ops.rcon_command(server, command, timeout=timeout)


def rcon_quiet(server: GameServer, command: str, timeout: float = 10.0) -> None:
    try:
        rcon(server, command, timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("%s: rcon %r failed: %s", server.slug, command, exc)


# ── Backups ───────────────────────────────────────────────────────────────────

def folder_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def make_backup(session: Session, server: GameServer, backup: ServerBackup) -> None:
    backup.status = "running"
    backup.started_at = now()
    backup.error = None
    backup.progress = "Готовлюсь"
    session.commit()
    try:
        _archive(session, server, backup)
    except Exception as exc:  # noqa: BLE001
        backup.status = "failed"
        backup.error = str(exc) if isinstance(exc, Failed) else f"{type(exc).__name__}: {exc}"
        backup.progress = None
        backup.finished_at = now()
        session.commit()
        log.error("%s: backup %s failed: %s", server.slug, backup.id, backup.error)
        if not isinstance(exc, Failed):
            traceback.print_exc()
        raise


def _archive(session: Session, server: GameServer, backup: ServerBackup) -> None:
    data_dir = server_ops.resolve_data_dir(server)
    if not data_dir or not os.path.isdir(data_dir):
        raise Failed("Не найдена папка сервера")
    worlds = svc.world_folders(data_dir)
    if not worlds:
        raise Failed("В папке сервера нет миров (папок с level.dat)")
    backup.worlds = worlds

    raw = sum(folder_size(Path(data_dir) / w) for w in worlds)
    target_dir = svc.archive_dir(server.slug)
    target_dir.mkdir(parents=True, exist_ok=True)
    usage = svc.disk_usage(target_dir)
    # zstd shrinks a world to well under its size; budgeting all of it keeps the margin.
    if usage and usage["free"] - raw < svc.MIN_FREE_BYTES:
        raise Failed(
            f"Мало места на диске бэкапов: свободно {usage['free'] // 1024**3} ГБ, "
            f"мир {raw // 1024**3} ГБ, нужно оставить {svc.MIN_FREE_BYTES // 1024**3} ГБ"
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final = target_dir / f"{stamp}-{backup.kind}-{str(backup.id)[:8]}.tar.zst"
    tmp = final.with_suffix(final.suffix + ".tmp")

    live = running(server)
    paused_chunky = False
    try:
        if live:
            backup.progress = "Сохраняю мир"
            session.commit()
            try:
                if "Task running" in rcon(server, "chunky progress"):
                    rcon_quiet(server, "chunky pause")
                    paused_chunky = True
            except Exception:  # noqa: BLE001 — no Chunky, nothing to pause
                pass
            rcon(server, "save-off")
            # Answers once every level is on disk; a big world takes a while.
            rcon(server, "save-all flush", timeout=900)
        backup.progress = f"Архивирую {', '.join(worlds)} ({raw // 1024**2} МБ)"
        session.commit()
        tar = subprocess.Popen(
            ["tar", "-C", data_dir, "--warning=no-file-changed", "--warning=no-file-removed", "-cf", "-", *worlds],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        zst = subprocess.run(["zstd", "-T0", "-3", "-q", "-f", "-o", str(tmp)], stdin=tar.stdout,
                             capture_output=True)
        tar.stdout.close()
        tar_err = tar.stderr.read().decode(errors="replace")
        tar_rc = tar.wait()
    finally:
        if live:
            rcon_quiet(server, "save-on")
            if paused_chunky:
                rcon_quiet(server, "chunky continue")

    # tar exits 1 on "file changed as we read it" — a warning; 2 and up is fatal.
    if zst.returncode != 0 or tar_rc > 1 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise Failed(f"Архивация не удалась: tar={tar_rc} zstd={zst.returncode} {tar_err[:300]} {zst.stderr.decode(errors='replace')[:300]}")

    backup.progress = "Проверяю архив"
    session.commit()
    check = subprocess.run(["zstd", "-t", "-q", str(tmp)], capture_output=True)
    if check.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise Failed("Архив не прошёл проверку (zstd -t)")
    tmp.rename(final)

    backup.path = str(final)
    backup.size_bytes = final.stat().st_size
    backup.status = "done"
    backup.progress = None
    backup.finished_at = now()
    session.commit()
    log.info("%s: backup %s done, %s MB", server.slug, backup.id, backup.size_bytes // 1024**2)


# ── Restores ──────────────────────────────────────────────────────────────────

def say(server: GameServer, text: str) -> None:
    rcon_quiet(server, f"say {text}")


def restore(session: Session, server: GameServer, job: ServerBackupRestore) -> None:
    job.status = "running"
    job.started_at = now()
    session.commit()

    def step(text: str) -> None:
        job.step = text
        session.commit()
        log.info("%s: restore %s: %s", server.slug, job.id, text)

    backup = session.get(ServerBackup, job.backup_id)
    data_dir = server_ops.resolve_data_dir(server)
    staging = Path(data_dir or "/nonexistent") / f"{STAGING}{str(job.id)[:8]}"
    replaced = Path(data_dir or "/nonexistent") / f"{OLD}{str(job.id)[:8]}"
    flag = Path(data_dir or "/nonexistent") / "maintenance.flag"
    set_flag = False
    try:
        if backup is None or backup.status != "done" or not backup.path or not os.path.isfile(backup.path):
            raise Failed("Файл бэкапа не найден")
        if not data_dir or not os.path.isdir(data_dir):
            raise Failed("Не найдена папка сервера")
        worlds = list(backup.worlds or [])
        if not worlds:
            raise Failed("В бэкапе не записано, какие миры в нём лежат")

        # 1. A backup of the world as it is, so this restore can be undone.
        step("Делаю бэкап текущего мира, чтобы откат можно было отменить")
        pre = ServerBackup(server_id=server.id, kind="pre_restore", status="pending", worlds=[],
                           note=f"Перед откатом на бэкап от {backup.created_at.astimezone().strftime('%d.%m %H:%M')}",
                           created_by=job.requested_by)
        session.add(pre)
        session.commit()
        job.pre_backup_id = pre.id
        session.commit()
        try:
            make_backup(session, server, pre)
        except Exception as exc:  # noqa: BLE001
            raise Failed(f"Бэкап перед откатом не удался: {pre.error or exc}. Мир не тронут.")

        # 2. Unpack next to the server — the same disk, so the swap is a rename.
        step("Распаковываю бэкап")
        archive_size = os.path.getsize(backup.path)
        usage = svc.disk_usage(Path(data_dir))
        if usage and usage["free"] < archive_size * 4:
            raise Failed(f"Мало места на диске сервера для распаковки: свободно {usage['free'] // 1024**3} ГБ")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        unpack = subprocess.run(
            f"zstd -dc -q '{backup.path}' | tar -xf - -C '{staging}'", shell=True, capture_output=True, text=True,
        )
        if unpack.returncode != 0:
            raise Failed(f"Не удалось распаковать: {unpack.stderr[:300]}")
        missing = [w for w in worlds if not (staging / w / "level.dat").is_file()]
        if missing:
            raise Failed(f"В архиве нет миров: {', '.join(missing)}")

        # 3. Stop the server — the watchdog told it is maintenance, not a crash.
        if not flag.exists():
            flag.write_text(f"backup restore {job.id}\n")
            set_flag = True
        was_running = running(server)
        if was_running:
            warn = max(0, job.warn_seconds)
            step(f"Предупреждаю игроков ({warn} с) и останавливаю сервер")
            if warn:
                say(server, f"§c§lСервер будет перезапущен через {warn} с — откат мира на бэкап.")
                for left in (30, 10, 5):
                    if left < warn:
                        time.sleep(warn - left)
                        warn = left
                        say(server, f"§cПерезапуск через {left} с.")
                time.sleep(warn)
            rcon_quiet(server, "stop", timeout=30)
            deadline = time.monotonic() + 900
            # Until the process is gone, not merely "deactivating": the JVM still
            # holds the world while it saves and shuts down.
            while unit_state(server)[2] > 0:
                if time.monotonic() > deadline:
                    raise Failed("Сервер не остановился за 15 минут — мир не тронут, проверьте его")
                time.sleep(0.5)

        # 4. The swap, while systemd waits to start it again. Make sure nothing is
        #    running on these folders right now.
        state, sub, pid = unit_state(server)
        if pid:
            raise Failed(f"Сервер снова запущен ({state}/{sub}) раньше подмены — мир не тронут")
        step("Подменяю мир")
        replaced.mkdir(exist_ok=True)
        moved: list[str] = []
        try:
            for w in worlds:
                live_path = Path(data_dir) / w
                if live_path.exists():
                    live_path.rename(replaced / w)
                    moved.append(w)
                (staging / w).rename(live_path)
        except Exception as exc:
            # Put back whatever was moved, so the server starts on its own world.
            for w in worlds:
                live_path = Path(data_dir) / w
                if w in moved and (replaced / w).exists():
                    if live_path.exists():
                        shutil.rmtree(live_path, ignore_errors=True)
                    (replaced / w).rename(live_path)
            raise Failed(f"Подмена не удалась, мир возвращён как был: {exc}")

        # 5. systemd starts it (Restart=always); wait until it answers.
        if was_running:
            step("Мир подменён, жду запуска сервера")
            deadline = time.monotonic() + 1800
            up = False
            while time.monotonic() < deadline:
                if running(server):
                    try:
                        rcon(server, "list", timeout=5)
                        up = True
                        break
                    except Exception:  # noqa: BLE001 — still booting
                        pass
                time.sleep(5)
            if not up:
                raise Failed("Мир подменён, но сервер не поднялся за 30 минут — проверьте его (бэкап «перед откатом» сохранён)")
            done_text = "Готово: сервер запущен на мире из бэкапа"
        else:
            done_text = "Готово: мир подменён. Сервер был выключен — запустите его"

        shutil.rmtree(replaced, ignore_errors=True)
        job.status = "done"
        job.step = done_text
        job.finished_at = now()
        session.commit()
        log.info("%s: restore %s done", server.slug, job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc) if isinstance(exc, Failed) else f"{type(exc).__name__}: {exc}"
        job.finished_at = now()
        session.commit()
        log.error("%s: restore %s failed: %s", server.slug, job.id, job.error)
        if not isinstance(exc, Failed):
            traceback.print_exc()
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if set_flag:
            flag.unlink(missing_ok=True)


# ── Schedule and pruning ──────────────────────────────────────────────────────

def settings_of(session: Session, server: GameServer) -> dict:
    row = session.query(ServerBackupSettings).filter(ServerBackupSettings.server_id == server.id).one_or_none()
    return {**default_backup_settings(), **(row.config if row else {})}


def schedule_due(session: Session) -> None:
    for server in session.query(GameServer).all():
        cfg = settings_of(session, server)
        if not cfg.get("enabled"):
            continue
        last = (
            session.query(ServerBackup)
            .filter(ServerBackup.server_id == server.id, ServerBackup.kind == "scheduled",
                    ServerBackup.status.in_(("pending", "running", "done")))
            .order_by(ServerBackup.created_at.desc()).first()
        )
        if last is None or now() - last.created_at >= timedelta(hours=int(cfg["every_hours"])):
            session.add(ServerBackup(server_id=server.id, kind="scheduled", status="pending", worlds=[],
                                     note="По расписанию", created_by="расписание"))
            session.commit()


def prune(session: Session) -> None:
    for server in session.query(GameServer).all():
        keep = int(settings_of(session, server)["keep"])
        old = (
            session.query(ServerBackup)
            .filter(ServerBackup.server_id == server.id, ServerBackup.kind == "scheduled", ServerBackup.status == "done")
            .order_by(ServerBackup.created_at.desc()).offset(keep).all()
        )
        for b in old:
            in_use = session.query(ServerBackupRestore).filter(
                ServerBackupRestore.backup_id == b.id, ServerBackupRestore.status.in_(("pending", "running"))
            ).first()
            if in_use:
                continue
            if b.path and os.path.isfile(b.path) and svc.within_backup_root(b.path):
                os.remove(b.path)
            session.delete(b)
            session.commit()
            log.info("%s: pruned scheduled backup %s", server.slug, b.id)
        # Failed scheduled attempts only clutter the list after a day.
        session.query(ServerBackup).filter(
            ServerBackup.server_id == server.id, ServerBackup.kind == "scheduled", ServerBackup.status == "failed",
            ServerBackup.created_at < now() - timedelta(days=1),
        ).delete(synchronize_session=False)
        session.commit()


def recover(session: Session) -> None:
    """Jobs left "running" by a worker that died: nobody holds the lock but us now."""
    for b in session.query(ServerBackup).filter(ServerBackup.status == "running").all():
        server = session.get(GameServer, b.server_id)
        if server is not None:
            rcon_quiet(server, "save-on")  # it may have died between save-off and save-on
        b.status = "failed"
        b.error = "Исполнитель прервался посреди бэкапа (перезапуск машины или бэкенда)"
        b.finished_at = now()
    for r in session.query(ServerBackupRestore).filter(ServerBackupRestore.status == "running").all():
        r.status = "failed"
        r.error = f"Исполнитель прервался на шаге «{r.step}». Проверьте папку сервера: {STAGING}* / {OLD}*"
        r.finished_at = now()
    session.commit()


# ── Run ───────────────────────────────────────────────────────────────────────

def run_once(session: Session) -> bool:
    """Does one thing, if there is anything to do. Returns whether it did."""
    job = (session.query(ServerBackupRestore).filter(ServerBackupRestore.status == "pending")
           .order_by(ServerBackupRestore.created_at).first())
    if job is not None:
        restore(session, session.get(GameServer, job.server_id), job)
        return True
    backup = (session.query(ServerBackup).filter(ServerBackup.status == "pending")
              .order_by(ServerBackup.created_at).first())
    if backup is not None:
        try:
            make_backup(session, session.get(GameServer, backup.server_id), backup)
        except Exception:  # noqa: BLE001 — recorded on the row
            pass
        return True
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0  # the previous run is still busy
    session = SessionLocal()
    try:
        recover(session)
        schedule_due(session)
        while run_once(session):
            schedule_due(session)
        prune(session)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
