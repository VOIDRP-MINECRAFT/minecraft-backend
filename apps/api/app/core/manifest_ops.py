"""Async manifest-regeneration job for the admin «Моды» tab.

The old path ran ``generate_launcher_manifest`` synchronously (blocking the HTTP
request up to 5 min with no feedback). This runs it as a detached child of the
backend, streaming stdout to a log file, so the admin UI can poll
:func:`get_status` for a live console + a %-bar. The generator emits
``[[MANIFEST_PROGRESS]] done/total`` markers (see scripts/generate_launcher_manifest.py)
that drive the bar; a shell sentinel line records the exit code so success/failure
is known without a waiter thread. Only one job runs at a time (global).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone

from apps.api.app.core import mod_ops
from apps.api.app.models.game_server import GameServer

_JOB_DIR = os.path.join(mod_ops.REPO_ROOT, ".manifest-job")
_LOG = os.path.join(_JOB_DIR, "regen.log")
_STATUS = os.path.join(_JOB_DIR, "status.json")

_PROGRESS_RE = re.compile(r"\[\[MANIFEST_PROGRESS\]\]\s+(\d+)/(\d+)")
_DONE_RE = re.compile(r"==MANIFEST_DONE rc=(-?\d+)==")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_status() -> dict:
    try:
        with open(_STATUS, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_status(data: dict) -> None:
    os.makedirs(_JOB_DIR, exist_ok=True)
    tmp = _STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _STATUS)


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def tail_log(max_bytes: int = 256 * 1024) -> str:
    try:
        size = os.path.getsize(_LOG)
        with open(_LOG, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # drop partial first line
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def start(server: GameServer) -> dict:
    """Spawn the per-server manifest rebuild detached. Raises ModOpsError if a
    job is already running or the command can't be built."""
    if get_status(include_log=False).get("running"):
        raise mod_ops.ModOpsError("Пересборка уже идёт — дождитесь завершения.")

    cmd = mod_ops._regen_command(server)  # may raise ModOpsError (bad script)
    os.makedirs(_JOB_DIR, exist_ok=True)
    open(_LOG, "w", encoding="utf-8").close()  # truncate for the new run

    # Wrap so the child appends an exit sentinel to the log; the poller reads it
    # to mark success/failure — no waiter thread needed.
    quoted = " ".join(shlex.quote(c) for c in cmd)
    wrapped = f'{quoted}; ec=$?; printf "\\n==MANIFEST_DONE rc=%s==\\n" "$ec"; exit "$ec"'
    env = {**os.environ, "PATH": mod_ops._SAFE_PATH, "PYTHONUNBUFFERED": "1"}

    status = {
        "state": "running",
        "slug": server.slug,
        "server_name": server.name,
        "pid": None,
        "started_at": _now(),
        "finished_at": None,
        "error": None,
    }
    _write_status(status)

    with open(_LOG, "ab") as log_fh:
        proc = subprocess.Popen(
            [mod_ops._BASH, "-c", wrapped],
            cwd=mod_ops.REPO_ROOT,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    status["pid"] = proc.pid
    _write_status(status)
    return get_status()


def _percent(full_log: str, state: str | None) -> int:
    if state == "success":
        return 100
    percent = 0
    for m in _PROGRESS_RE.finditer(full_log):
        done, total = int(m.group(1)), int(m.group(2))
        percent = min(99, round(done / total * 100)) if total else 0
    return percent


def get_status(include_log: bool = True) -> dict:
    """Current/last job status. Resolves a stale `running` via the exit sentinel
    or a dead pid, computes a %-bar, and (optionally) returns the console log with
    internal markers stripped."""
    st = _read_status()
    full = tail_log(1024 * 1024)

    if st.get("state") == "running":
        done = _DONE_RE.search(full)
        if done:
            rc = int(done.group(1))
            st["state"] = "success" if rc == 0 else "error"
            st["running"] = False
            st["finished_at"] = st.get("finished_at") or _now()
            if rc != 0:
                st["error"] = f"Пересборка завершилась с ошибкой (код {rc})."
            _write_status(st)
        elif not _pid_alive(st.get("pid")):
            st["state"] = "error"
            st["running"] = False
            st["finished_at"] = _now()
            st["error"] = "Процесс пересборки завершился неожиданно."
            _write_status(st)
        else:
            st["running"] = True
    else:
        st["running"] = False

    payload = {
        "running": bool(st.get("running")),
        "state": st.get("state"),
        "slug": st.get("slug"),
        "server_name": st.get("server_name"),
        "error": st.get("error"),
        "started_at": st.get("started_at"),
        "finished_at": st.get("finished_at"),
        "percent": _percent(full, st.get("state")),
    }
    if include_log:
        lines = [
            ln for ln in full.splitlines()
            if not ln.startswith("[[MANIFEST_PROGRESS]]") and "==MANIFEST_DONE" not in ln
        ]
        payload["log"] = "\n".join(lines)
    return payload
