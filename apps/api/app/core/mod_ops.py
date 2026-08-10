"""Filesystem operations for the admin "Моды" panel.

Each server keeps mods in two independent places:
  * client pack:  ``<pack_root>/mods``   — synced to players via the manifest
  * server mods:  ``<data_dir>/mods``    — loaded by the game server (needs restart)

This module is the ONLY thing that writes to those dirs from the backend, and it
is deliberately paranoid:

  * every file name is reduced to a basename and validated (``.jar`` only, no
    path separators, no ``..``) — callers can't escape the target dir;
  * writes are atomic (temp file in the same dir + ``os.replace``);
  * deletes are soft — the jar is *moved* to a timestamped trash dir so a mistake
    is recoverable;
  * staging and trash live OUTSIDE any pack_root, so a half-applied upload can
    never leak into a generated manifest;
  * manifest regeneration is dispatched by an explicit per-slug command — abyss
    uses its own script, everything else the DB-driven generator; we never run
    ``--all`` (it corrupts abyss) and never guess.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.server_mod import ServerModMeta

REPO_ROOT = "/home/mironoouv/minecraft"
VENV_PY = os.path.join(REPO_ROOT, "minecraft_backend/.venv/bin/python")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
# Staging + trash roots, intentionally outside /home/mironoouv/launcher so they
# are never scanned into a manifest. Same filesystem as the client pack (home),
# so moves into pack/mods are cheap; copies to /mnt/ssd server dirs cross fs fine.
OPS_BASE = "/home/mironoouv/voidrp_mod_ops"

_JAR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+ \-]*\.jar$")
_MAX_JAR_BYTES = 300 * 1024 * 1024  # 300 MB hard cap per jar


class ModOpsError(RuntimeError):
    """User-facing (already Russian) error for a mod operation."""


# ── Name validation ──────────────────────────────────────────────────────────
def sanitize_jar(name: str) -> str:
    base = (name or "").strip()
    if base != os.path.basename(base) or "/" in base or "\\" in base or ".." in base:
        raise ModOpsError(f"Недопустимое имя файла: {name!r}")
    if not _JAR_RE.match(base):
        raise ModOpsError(f"Ожидается .jar-файл, получено: {name!r}")
    return base


# ── Directory resolution (with existence guards) ─────────────────────────────
def client_mods_dir(server: GameServer) -> str:
    if not server.pack_root:
        raise ModOpsError("Для сервера не задан pack_root")
    d = os.path.join(server.pack_root, "mods")
    if not os.path.isdir(d):
        raise ModOpsError(f"Папка клиентских модов не найдена: {d}")
    return d


def server_mods_dir(server: GameServer) -> str:
    data = server_ops.resolve_data_dir(server)
    if not data:
        raise ModOpsError("Не удалось определить рабочую папку сервера (data_dir/systemd unit)")
    d = os.path.join(data, "mods")
    if not os.path.isdir(d):
        raise ModOpsError(f"Папка серверных модов не найдена: {d}")
    return d


def _has_server_dir(server: GameServer) -> bool:
    try:
        server_mods_dir(server)
        return True
    except ModOpsError:
        return False


# ── Atomic write / copy / soft-delete ────────────────────────────────────────
def _atomic_write(dest_path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = f"{dest_path}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _atomic_copy(src_path: str, dest_path: str) -> None:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = f"{dest_path}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        shutil.copy2(src_path, tmp)
        os.replace(tmp, dest_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _trash(slug: str, side: str, file_path: str) -> str:
    """Move a jar into a timestamped trash dir (recoverable). Returns new path."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    trash_dir = os.path.join(OPS_BASE, "trash", slug, side, ts)
    os.makedirs(trash_dir, exist_ok=True)
    dest = os.path.join(trash_dir, os.path.basename(file_path))
    shutil.move(file_path, dest)
    return dest


# ── Classification (reuse the generator so the UI shows real effective flags) ─
_gen_module = None


def _generator():
    global _gen_module
    if _gen_module is None:
        import importlib.util

        path = os.path.join(SCRIPTS_DIR, "generate_launcher_manifest.py")
        spec = importlib.util.spec_from_file_location("voidrp_manifest_gen", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _gen_module = mod
    return _gen_module


def _fallback_classification(filename: str) -> dict:
    """Effective optional/required for a jar with no admin override, using the
    generator's built-in dicts — so existing pack mods show their real state."""
    try:
        cls = _generator().classify_mod(f"mods/{filename}", None)
    except Exception:
        cls = None
    if cls and cls.get("optional"):
        return {
            "optional": True,
            "required": bool(cls.get("required")),
            "display_name": cls.get("displayName"),
            "description": cls.get("description"),
            "source": "auto",
        }
    return {"optional": False, "required": False, "display_name": None, "description": None, "source": "hidden"}


# ── Listing ──────────────────────────────────────────────────────────────────
@dataclass
class ModEntry:
    filename: str
    on_client: bool
    on_server: bool
    size: int
    optional: bool
    required: bool
    display_name: str | None
    description: str | None
    source: str  # "override" | "auto" | "hidden"

    def as_dict(self) -> dict:
        return self.__dict__


def _scan_jars(directory: str) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        for name in os.listdir(directory):
            if name.lower().endswith(".jar") and os.path.isfile(os.path.join(directory, name)):
                out[name] = os.path.getsize(os.path.join(directory, name))
    except OSError:
        pass
    return out


def list_mods(session: Session, server: GameServer) -> dict:
    client_dir = client_mods_dir(server)
    client = _scan_jars(client_dir)
    server_present = _has_server_dir(server)
    srv = _scan_jars(server_mods_dir(server)) if server_present else {}

    overrides = {
        m.filename: m
        for m in session.scalars(
            select(ServerModMeta).where(ServerModMeta.server_id == server.id)
        )
    }

    entries: list[ModEntry] = []
    for name in sorted(set(client) | set(srv), key=str.lower):
        ov = overrides.get(name)
        if ov is not None:
            eff = {
                "optional": ov.optional,
                "required": ov.required,
                "display_name": ov.display_name,
                "description": ov.description,
                "source": "override",
            }
        else:
            eff = _fallback_classification(name)
        entries.append(ModEntry(
            filename=name,
            on_client=name in client,
            on_server=name in srv,
            size=client.get(name) or srv.get(name) or 0,
            **eff,
        ))

    return {
        "server_slug": server.slug,
        "client_mods_dir": client_dir,
        "server_mods_dir": server_mods_dir(server) if server_present else None,
        "server_dir_available": server_present,
        "counts": {
            "total": len(entries),
            "client": len(client),
            "server": len(srv),
            "optional": sum(1 for e in entries if e.optional),
        },
        "mods": [e.as_dict() for e in entries],
    }


# ── Metadata upsert ──────────────────────────────────────────────────────────
def upsert_meta(
    session: Session,
    server: GameServer,
    filename: str,
    *,
    optional: bool,
    required: bool,
    display_name: str | None,
    description: str | None,
    updated_by: str | None,
) -> ServerModMeta:
    row = session.scalar(
        select(ServerModMeta).where(
            ServerModMeta.server_id == server.id, ServerModMeta.filename == filename
        )
    )
    if row is None:
        row = ServerModMeta(server_id=server.id, filename=filename)
        session.add(row)
    row.optional = bool(optional)
    row.required = bool(required and optional)  # required only meaningful when optional
    row.display_name = (display_name or None)
    row.description = (description or None)
    row.updated_by = updated_by
    session.flush()
    return row


def delete_meta(session: Session, server: GameServer, filename: str) -> None:
    row = session.scalar(
        select(ServerModMeta).where(
            ServerModMeta.server_id == server.id, ServerModMeta.filename == filename
        )
    )
    if row is not None:
        session.delete(row)
        session.flush()


# ── Staging (upload → review → apply) ────────────────────────────────────────
def stage_uploads(slug: str, files: list[tuple[str, bytes]]) -> dict:
    if not files:
        raise ModOpsError("Не выбрано ни одного файла")
    token = uuid.uuid4().hex[:16]
    d = os.path.join(OPS_BASE, "staging", slug, token)
    os.makedirs(d, exist_ok=True)
    entries = []
    for fname, data in files:
        base = sanitize_jar(fname)
        if len(data) > _MAX_JAR_BYTES:
            raise ModOpsError(f"Файл слишком большой (>300 МБ): {base}")
        if len(data) < 100:
            raise ModOpsError(f"Файл пустой или повреждён: {base}")
        _atomic_write(os.path.join(d, base), data)
        entries.append({"filename": base, "size": len(data)})
    return {"token": token, "files": entries}


def _staging_dir(slug: str, token: str) -> str:
    # token is opaque hex we generated; still validate to avoid traversal.
    if not re.fullmatch(r"[0-9a-f]{16}", token or ""):
        raise ModOpsError("Некорректный токен загрузки")
    d = os.path.join(OPS_BASE, "staging", slug, token)
    if not os.path.isdir(d):
        raise ModOpsError("Сессия загрузки не найдена или устарела")
    return d


def apply_staged(
    session: Session,
    server: GameServer,
    token: str,
    selections: list[dict],
    updated_by: str | None,
) -> dict:
    """Copy each staged jar into the chosen dirs and record its metadata."""
    staging = _staging_dir(server.slug, token)
    applied: list[str] = []
    for sel in selections:
        base = sanitize_jar(sel["filename"])
        src = os.path.join(staging, base)
        if not os.path.isfile(src):
            raise ModOpsError(f"Файл не найден в загрузке: {base}")
        on_client = bool(sel.get("on_client"))
        on_server = bool(sel.get("on_server"))
        if not on_client and not on_server:
            continue  # nothing to do for this file
        if on_client:
            _atomic_copy(src, os.path.join(client_mods_dir(server), base))
        if on_server:
            _atomic_copy(src, os.path.join(server_mods_dir(server), base))
        upsert_meta(
            session, server, base,
            optional=bool(sel.get("optional")),
            required=bool(sel.get("required")),
            display_name=sel.get("display_name"),
            description=sel.get("description"),
            updated_by=updated_by,
        )
        applied.append(base)
    # Best-effort cleanup of the whole staging token dir.
    shutil.rmtree(staging, ignore_errors=True)
    return {"applied": applied, "count": len(applied)}


# ── Toggle client/server presence for an existing mod ────────────────────────
def set_targets(server: GameServer, filename: str, on_client: bool, on_server: bool) -> dict:
    base = sanitize_jar(filename)
    cpath = os.path.join(client_mods_dir(server), base)
    spath = os.path.join(server_mods_dir(server), base) if _has_server_dir(server) else None
    has_c = os.path.isfile(cpath)
    has_s = bool(spath and os.path.isfile(spath))
    if on_server and spath is None:
        raise ModOpsError("Папка серверных модов недоступна для этого сервера")

    source = cpath if has_c else (spath if has_s else None)
    if source is None:
        raise ModOpsError(f"Файл мода не найден: {base}")

    changed: list[str] = []
    if on_client and not has_c:
        _atomic_copy(source, cpath); changed.append("client+")
    elif not on_client and has_c:
        _trash(server.slug, "client", cpath); changed.append("client-")
    if spath is not None:
        if on_server and not has_s:
            _atomic_copy(source, spath); changed.append("server+")
        elif not on_server and has_s:
            _trash(server.slug, "server", spath); changed.append("server-")
    return {"filename": base, "changed": changed}


# ── Remove (soft) ─────────────────────────────────────────────────────────────
def remove_mod(session: Session, server: GameServer, filename: str, target: str) -> dict:
    base = sanitize_jar(filename)
    removed: list[str] = []
    if target in ("client", "both"):
        cpath = os.path.join(client_mods_dir(server), base)
        if os.path.isfile(cpath):
            _trash(server.slug, "client", cpath); removed.append("client")
    if target in ("server", "both") and _has_server_dir(server):
        spath = os.path.join(server_mods_dir(server), base)
        if os.path.isfile(spath):
            _trash(server.slug, "server", spath); removed.append("server")
    if not removed:
        raise ModOpsError(f"Файл мода не найден для удаления: {base}")
    if target == "both":
        delete_meta(session, server, base)
    return {"filename": base, "removed": removed}


# ── Manifest regeneration (explicit per-slug dispatch) ───────────────────────
# A normal PATH for the regen subprocess: the backend runs as a systemd service
# with PATH narrowed to the venv bin, so the abyss shell script (bash, python3,
# cat, ls ...) can't find its tools otherwise. We call bash by absolute path AND
# hand the child a full PATH so its own bare commands resolve.
_BASH = "/bin/bash" if os.path.exists("/bin/bash") else "/usr/bin/bash"
_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _regen_command(server: GameServer) -> list[str]:
    """Per-server rebuild command, driven by DB (not hardcoded by slug).

    ``game_servers.manifest_build_script`` set → run that bash script (must live
    under scripts/); otherwise the standard DB-driven generator. Never ``--all``.
    """
    script = (getattr(server, "manifest_build_script", None) or "").strip()
    if script:
        path = script if os.path.isabs(script) else os.path.join(REPO_ROOT, script)
        real = os.path.realpath(path)
        # Confine to scripts/ so a DB value can't point the runner at an arbitrary
        # binary elsewhere on the box.
        if not real.startswith(SCRIPTS_DIR + os.sep) or not os.path.isfile(real):
            raise ModOpsError(f"Некорректный скрипт пересборки манифеста: {script}")
        return [_BASH, real]
    return [VENV_PY, os.path.join(SCRIPTS_DIR, "generate_launcher_manifest.py"),
            "--server-slug", server.slug]


def regenerate_manifest(server: GameServer, timeout: float = 300.0) -> dict:
    cmd = _regen_command(server)
    env = {**os.environ, "PATH": _SAFE_PATH}
    try:
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                             timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise ModOpsError("Пересборка манифеста превысила таймаут")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ModOpsError(f"Не удалось запустить пересборку: {exc}")
    out = (res.stdout or "")[-4000:]
    err = (res.stderr or "")[-2000:]
    if res.returncode != 0:
        raise ModOpsError(f"Пересборка завершилась с ошибкой (код {res.returncode}). {err.strip()[:500]}")
    return {"ok": True, "slug": server.slug, "stdout_tail": out, "stderr_tail": err}
