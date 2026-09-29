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

from apps.api.app.core import server_changes, server_ops
from apps.api.app.db import SessionLocal
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_change import ServerRestartJob
from apps.api.app.models.server_backup import (
    ServerBackup,
    ServerBackupRestore,
    ServerBackupSettings,
    default_backup_settings,
)
from apps.api.app.services import backups as svc

log = logging.getLogger("backup-worker")

LOCK = "/tmp/voidrp-backup-worker.lock"
BACKGROUND = ["nice", "-n", "19", "ionice", "-c", "3"]
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
        # Lowest CPU and disk priority, two compression threads: the game server on the
        # same machine comes first — a 55 GB world at full tilt made it lag. Level 1:
        # region files are compressed already, a higher level only costs time. The stream
        # is checked on its way to the disk (tee → zstd -t) rather than read back after,
        # which on the backup HDD took as long as the archiving itself.
        script = (
            'tar -C "$1" --warning=no-file-changed --warning=no-file-removed -cf - "${@:3}" '
            '| zstd -T2 -1 -q -c | tee "$2" | zstd -t -q; '
            'echo "${PIPESTATUS[*]}" >&2'
        )
        pipe = subprocess.run(
            [*BACKGROUND, "bash", "-c", script, "backup", data_dir, str(tmp), *worlds],
            capture_output=True, text=True,
        )
        codes = (pipe.stderr.strip().splitlines() or [""])[-1].split()
        tar_rc, zst_rc, tee_rc, check_rc = ([int(c) for c in codes] + [99, 99, 99, 99])[:4]
        tar_err = pipe.stderr
    finally:
        if live:
            rcon_quiet(server, "save-on")
            if paused_chunky:
                rcon_quiet(server, "chunky continue")

    # tar exits 1 on "file changed as we read it" — a warning; 2 and up is fatal.
    if zst_rc != 0 or tee_rc != 0 or tar_rc > 1 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise Failed(f"Архивация не удалась: tar={tar_rc} zstd={zst_rc} tee={tee_rc} {tar_err[-400:]}")
    if check_rc != 0:
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
                           note=f"Перед откатом на бэкап от {(backup.finished_at or backup.created_at).astimezone().strftime('%d.%m %H:%M')}",
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
            f"nice -n 19 zstd -dc -q '{backup.path}' | nice -n 19 tar -xf - -C '{staging}'",
            shell=True, capture_output=True, text=True,
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


# ── Mods and plugins: applying the queue in a restart ─────────────────────────

def restart_apply(session: Session, server: GameServer, job: ServerRestartJob) -> None:
    """Warn, stop, put the queued jar changes in place while the server is down (in the
    15 s before systemd starts it again), wait until it answers. The same way a backup
    is restored — the jars are never touched under a running JVM."""
    job.status = "running"
    job.started_at = now()
    session.commit()

    def step(text: str) -> None:
        job.step = text
        session.commit()
        log.info("%s: restart job %s: %s", server.slug, job.id, text)

    data_dir = server_ops.resolve_data_dir(server)
    flag = Path(data_dir or "/nonexistent") / "maintenance.flag"
    set_flag = False
    try:
        if not server_changes.pending(session, server):
            raise Failed("Очередь пуста — применять нечего")
        if flag.parent.is_dir() and not flag.exists():
            flag.write_text(f"restart to apply mods/plugins {job.id}\n")
            set_flag = True
        was_running = running(server)
        if was_running:
            warn = max(0, job.warn_seconds)
            step(f"Предупреждаю игроков ({warn} с) и останавливаю сервер")
            if warn:
                say(server, f"§e§lСервер перезапустится через {warn} с — обновление модов и плагинов.")
                for left in (30, 10, 5):
                    if left < warn:
                        time.sleep(warn - left)
                        warn = left
                        say(server, f"§eПерезапуск через {left} с.")
                time.sleep(warn)
            rcon_quiet(server, "stop", timeout=30)
            deadline = time.monotonic() + 900
            while unit_state(server)[2] > 0:
                if time.monotonic() > deadline:
                    raise Failed("Сервер не остановился за 15 минут — ничего не менял, проверьте его")
                time.sleep(0.5)
        state, sub, pid = unit_state(server)
        if pid:
            raise Failed(f"Сервер снова запущен ({state}/{sub}) раньше подмены — ничего не менял, очередь сохранена")
        step("Применяю изменения")
        applied = server_changes.apply_pending(session, server)
        failed = [c for c in applied if c.status == "failed"]
        summary = f"применено {len(applied) - len(failed)} из {len(applied)}"
        if was_running:
            step(f"Изменения: {summary}. Жду запуска сервера")
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
                raise Failed(f"Изменения: {summary}, но сервер не поднялся за 30 минут — проверьте его")
            done_text = f"Готово: {summary}, сервер запущен"
        else:
            done_text = f"Готово: {summary}. Сервер был выключен — запустите его"
        if failed:
            done_text += ". Не удалось: " + "; ".join(f"{c.filename}: {c.result}" for c in failed)
        job.status = "done"
        job.step = done_text
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc) if isinstance(exc, Failed) else f"{type(exc).__name__}: {exc}"
        if not isinstance(exc, Failed):
            traceback.print_exc()
    finally:
        job.finished_at = now()
        session.commit()
        if set_flag:
            flag.unlink(missing_ok=True)


def apply_when_stopped(session: Session) -> None:
    """Queued jar changes of a server found stopped are applied there and then."""
    from apps.api.app.models.server_change import ServerFileChange

    ids = {sid for (sid,) in session.query(ServerFileChange.server_id).filter(ServerFileChange.status == "pending").distinct()}
    for server_id in ids:
        server = session.get(GameServer, server_id)
        if server is None or not server.systemd_unit:
            continue
        busy = session.query(ServerRestartJob).filter(
            ServerRestartJob.server_id == server_id, ServerRestartJob.status.in_(("pending", "running"))).first()
        if busy is None and unit_state(server)[2] == 0:
            state, _sub, _pid = unit_state(server)
            if state in ("inactive", "failed"):
                applied = server_changes.apply_pending(session, server)
                log.info("%s: server stopped, applied %d queued jar changes", server.slug, len(applied))


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
    for j in session.query(ServerRestartJob).filter(ServerRestartJob.status == "running").all():
        j.status = "failed"
        j.error = f"Исполнитель прервался на шаге «{j.step}». Очередь изменений сохранена — проверьте сервер"
        j.finished_at = now()
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
    rj = (session.query(ServerRestartJob).filter(ServerRestartJob.status == "pending")
          .order_by(ServerRestartJob.created_at).first())
    if rj is not None:
        restart_apply(session, session.get(GameServer, rj.server_id), rj)
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
        apply_when_stopped(session)
        schedule_due(session)
        while run_once(session):
            schedule_due(session)
        prune(session)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
