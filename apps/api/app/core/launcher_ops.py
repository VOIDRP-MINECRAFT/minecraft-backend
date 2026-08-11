"""Launcher build & deploy operations for the admin "Лаунчер" tab.

The backend runs as the same OS user that owns the launcher repo and the web
deploy directory, so it can drive the existing `build-release-linux.sh` +
`deploy-launcher.sh` pipeline directly and publish a release without sudo.

A deploy is a long (minutes) CPU-heavy job, so it is spawned as a **detached**
subprocess writing to a log file; its lifecycle is tracked via a small
`status.json`. The admin UI polls `GET /admin/launcher/status` (+ `/log`) to show
the current stage live. Only one job may run at a time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from apps.api.app.config import get_settings

# ── Paths ────────────────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_STAGE_RE = re.compile(r"==>\s*(.+?)\s*$")

# Coarse progress: substring of the stage line → percent. First match wins, in
# order. Mirrors the stage banners printed by build-release-linux.sh /
# deploy-launcher.sh. Purely cosmetic ("что-то происходит").
_STAGE_PERCENT: list[tuple[str, int]] = [
    ("dotnet SDK", 3),
    ("Wine", 5),
    ("node", 6),
    ("Чистим", 8),
    ("node_modules", 10),
    ("dotnet restore", 12),
    ("CoreHost → win", 20),
    ("CoreHost → linux", 30),
    ("Updater → win", 38),
    ("Updater → linux", 44),
    ("Electron", 50),
    ("renderer", 58),
    ("Windows portable", 68),
    ("Linux AppImage", 78),
    ("артефакт", 84),
    ("manifest", 88),
    ("Публикуем в", 92),
    ("Проверяем", 96),
    ("Готово", 100),
]


def _repo() -> Path:
    return Path(get_settings().launcher_repo_dir)


def _deploy_dir() -> Path:
    return Path(get_settings().launcher_deploy_dir)


def _job_dir() -> Path:
    d = Path(get_settings().launcher_job_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_path() -> Path:
    return _job_dir() / "deploy.log"


def _status_path() -> Path:
    return _job_dir() / "status.json"


def _package_json() -> Path:
    return _repo() / "package.json"


def _deploy_script() -> Path:
    return _repo() / "deploy-launcher.sh"


def _notes_path() -> Path:
    return _job_dir() / "release-notes.txt"


def _history_path() -> Path:
    return _job_dir() / "history.jsonl"


def _prev_dir() -> Path:
    return _deploy_dir() / "prev"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Version ──────────────────────────────────────────────────────────────────


class LauncherOpsError(Exception):
    """Domain error → surfaced as 400/409 by the route layer."""


def read_current_version() -> str | None:
    try:
        data = json.loads(_package_json().read_text(encoding="utf-8"))
        return data.get("version")
    except (OSError, ValueError):
        return None


def validate_semver(v: str) -> str:
    v = (v or "").strip()
    if not _SEMVER_RE.match(v):
        raise LauncherOpsError("Версия должна быть в формате X.Y.Z (например 4.0.31)")
    return v


def bump_patch(v: str) -> str:
    major, minor, patch = v.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def set_version(new_version: str) -> str:
    """Rewrite the single `"version": "..."` line in package.json, preserving
    all other formatting. Refuses while a build is running."""
    new_version = validate_semver(new_version)
    job = get_job()
    if job.get("running"):
        raise LauncherOpsError("Идёт сборка — дождитесь её завершения перед сменой версии")

    path = _package_json()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LauncherOpsError(f"Не удалось прочитать package.json: {exc}") from exc

    new_text, n = re.subn(
        r'("version"\s*:\s*")[^"]*(")',
        lambda m: f"{m.group(1)}{new_version}{m.group(2)}",
        text,
        count=1,
    )
    if n != 1:
        raise LauncherOpsError("Не найдено поле version в package.json")
    path.write_text(new_text, encoding="utf-8")
    return new_version


# ── Release notes (shown to players in the update prompt) ────────────────────


def read_notes() -> str:
    try:
        return _notes_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def set_notes(text: str) -> str:
    text = (text or "").strip()
    if len(text) > 4000:
        raise LauncherOpsError("Слишком длинные заметки (макс 4000 символов)")
    _notes_path().write_text(text, encoding="utf-8")
    return text


# ── Deploy history ───────────────────────────────────────────────────────────


def read_history(limit: int = 20) -> list[dict]:
    """Most-recent-first list of past deploys (written by deploy-launcher.sh)."""
    try:
        lines = _history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


# ── Rollback (restore the previous published release) ────────────────────────


def read_prev_version() -> str | None:
    try:
        m = json.loads((_prev_dir() / "manifest.json").read_text(encoding="utf-8"))
        return m.get("version")
    except (OSError, ValueError):
        return None


def rollback() -> str:
    """Restore the previous release snapshot (kept in <deploy>/prev/) back to
    live, manifest LAST. Also syncs package.json to the restored version so the
    page stays consistent."""
    prev = _prev_dir()
    if not (prev / "manifest.json").exists():
        raise LauncherOpsError("Нет предыдущего релиза для отката")
    if get_job().get("running"):
        raise LauncherOpsError("Идёт сборка — дождитесь её завершения")

    import shutil

    dst = _deploy_dir()
    # Binaries first.
    for sub in ("win-x64", "linux-x64"):
        src_sub = prev / sub
        if not src_sub.is_dir():
            continue
        (dst / sub).mkdir(parents=True, exist_ok=True)
        for f in src_sub.iterdir():
            if f.is_file():
                tmp = dst / sub / (f.name + ".tmp")
                shutil.copy2(f, tmp)
                tmp.replace(dst / sub / f.name)
    # Public top-level downloads.
    for name in ("VoidRpLauncher.exe", "VoidRpLauncher"):
        src_f = prev / name
        if src_f.exists():
            tmp = dst / (name + ".tmp")
            shutil.copy2(src_f, tmp)
            tmp.replace(dst / name)
    # Manifest last.
    tmp = dst / "manifest.json.tmp"
    shutil.copy2(prev / "manifest.json", tmp)
    tmp.replace(dst / "manifest.json")

    version = read_deployed_manifest().get("version")
    if version and _SEMVER_RE.match(version):
        try:
            set_version(version)
        except LauncherOpsError:
            pass
    return version or "?"


# ── Deployed manifest inspection ─────────────────────────────────────────────


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().upper()
    except OSError:
        return None


def read_deployed_manifest() -> dict:
    """Parse the deployed manifest and, for each artifact, report on-disk size /
    mtime / sha256 and whether the disk sha matches the manifest (integrity)."""
    manifest_path = _deploy_dir() / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"present": False}

    artifacts: list[dict] = []
    for platform, entry in (manifest.get("artifacts") or {}).items():
        for kind in ("launcher", "updater"):
            spec = (entry or {}).get(kind)
            if not spec:
                continue
            url = spec.get("url", "")
            filename = url.rsplit("/", 1)[-1] if url else ""
            disk = _deploy_dir() / platform / filename
            manifest_sha = (spec.get("sha256") or "").upper()
            disk_sha = _sha256(disk)
            st = disk.stat() if disk.exists() else None
            artifacts.append(
                {
                    "platform": platform,
                    "kind": kind,
                    "filename": filename,
                    "sizeBytes": st.st_size if st else None,
                    "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
                    if st
                    else None,
                    "sha256Short": disk_sha[:16] if disk_sha else None,
                    "matches": bool(disk_sha and disk_sha == manifest_sha),
                    "exists": disk.exists(),
                }
            )

    return {
        "present": True,
        "version": manifest.get("version"),
        "notes": manifest.get("notes"),
        "artifacts": artifacts,
    }


# ── Job (build + deploy) ─────────────────────────────────────────────────────


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_status() -> dict:
    try:
        return json.loads(_status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(data: dict) -> None:
    tmp = _status_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_status_path())


def get_job() -> dict:
    """Current/last job status. Self-heals a stale `running` whose process died
    (e.g. the deploy script crashed hard without writing a final status)."""
    st = _read_status()
    state = st.get("state")
    running = state == "running"
    if running and not _pid_alive(st.get("pid")):
        # Process gone but the script never marked completion → treat as failed.
        st["state"] = "failed"
        st["finished_at"] = st.get("finished_at") or _now_iso()
        st["error"] = st.get("error") or "Процесс сборки завершился без финального статуса"
        _write_status(st)
        running = False
    st["running"] = running
    return st


def tail_log(max_bytes: int = 64 * 1024) -> str:
    path = _log_path()
    if not path.exists():
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        if size > max_bytes:
            nl = text.find("\n")
            if 0 <= nl < len(text) - 1:
                text = text[nl + 1 :]
        return _ANSI_RE.sub("", text)
    except OSError:
        return ""


def current_stage(log_text: str) -> tuple[str, int]:
    """Last `==>` banner in the log → (human stage, coarse percent)."""
    stage = ""
    for line in reversed(log_text.splitlines()):
        m = _STAGE_RE.search(_ANSI_RE.sub("", line))
        if m:
            stage = m.group(1)
            break
    percent = 0
    if stage:
        for needle, pct in _STAGE_PERCENT:
            if needle.lower() in stage.lower():
                percent = pct
                break
    return stage, percent


def _augmented_env() -> dict:
    """Env for the detached build: the systemd service PATH is narrowed, so we
    prepend the dotnet SDK dir and standard bins, and hand the script its deploy
    target + status file."""
    env = dict(os.environ)
    home = os.path.expanduser("~")
    extra_path = os.pathsep.join(
        [f"{home}/.dotnet", "/usr/local/bin", "/usr/bin", "/bin"]
    )
    env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    env["HOME"] = home
    env["LAUNCHER_DEPLOY_DIR"] = str(_deploy_dir())
    env["LAUNCHER_STATUS_FILE"] = str(_status_path())
    env["LAUNCHER_HISTORY_FILE"] = str(_history_path())
    env["LAUNCHER_RELEASE_NOTES"] = read_notes()
    return env


def start_deploy(actor: str) -> dict:
    """Spawn the build+deploy pipeline detached. Returns the initial job status.
    Raises LauncherOpsError(409-ish) if a job is already running."""
    job = get_job()
    if job.get("running"):
        raise LauncherOpsError("Сборка уже идёт")

    script = _deploy_script()
    if not script.exists():
        raise LauncherOpsError(f"Скрипт деплоя не найден: {script}")

    version = read_current_version()
    # Truncate the log for the new run.
    _log_path().write_text("", encoding="utf-8")
    status = {
        "state": "running",
        "pid": None,
        "version": version,
        "actor": actor,
        "started_at": _now_iso(),
        "finished_at": None,
        "error": None,
    }
    _write_status(status)

    log_fh = _log_path().open("ab")
    try:
        proc = subprocess.Popen(
            ["bash", "-lc", "exec ./deploy-launcher.sh"],
            cwd=str(_repo()),
            env=_augmented_env(),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        log_fh.close()

    status["pid"] = proc.pid
    _write_status(status)
    return get_job()


def stop_deploy() -> None:
    """Best-effort cancel of a running build (kills the whole process group)."""
    st = _read_status()
    pid = st.get("pid")
    if st.get("state") == "running" and _pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        st["state"] = "failed"
        st["finished_at"] = _now_iso()
        st["error"] = "Отменено администратором"
        _write_status(st)


def build_status_payload(include_log: bool = True) -> dict:
    """Full snapshot for GET /admin/launcher/status."""
    job = get_job()
    log_text = tail_log() if include_log else ""
    stage, percent = current_stage(log_text) if include_log else ("", 0)
    if job.get("state") == "success":
        percent = 100
    return {
        "currentVersion": read_current_version(),
        "deployed": read_deployed_manifest(),
        "notes": read_notes(),
        "prevVersion": read_prev_version(),
        "job": {
            "state": job.get("state"),
            "running": bool(job.get("running")),
            "version": job.get("version"),
            "actor": job.get("actor"),
            "startedAt": job.get("started_at"),
            "finishedAt": job.get("finished_at"),
            "error": job.get("error"),
            "stage": stage,
            "percent": percent,
        },
        "logTail": log_text if include_log else "",
    }
