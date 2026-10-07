"""Admin: the selected server's files — browse, read, edit with history, upload, download,
create, rename, delete. Everything inside the server's own folder only; the rules are
in services/server_files.py.

Permissions, per server: files.view (browse, read, download), files.edit (save text
files, revert), files.upload (upload, new folder, rename), files.delete, files.secrets
(see and download what is secret). Every change is written to the audit log.

Jars of mods and plugins are not touched here — they belong to the «Моды и плагины»
section; their configs are edited here. Any other jar changes only on a stopped server.
"""
from __future__ import annotations

import io
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.core.remote_files import RemoteFileError
from apps.api.app.services import remote_file_store as rfs
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import caller_permissions, get_current_staff_user, reauth_is_fresh, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.file_revision import FileRevision
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.services import server_files as sf

router = APIRouter(
    prefix="/admin/files",
    tags=["admin", "files"],
    dependencies=[Depends(require_permission("files.view"))],
)

UPLOAD_LIMIT = 200 * 1024 * 1024
ZIP_LIMIT = 500 * 1024 * 1024
KEEP_REVISIONS = 50


def _root(server: GameServer) -> Path:
    try:
        return sf.root_of(server_ops.resolve_data_dir(server))
    except sf.FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def _path(root: Path, rel: str | None, must_exist: bool = True) -> Path:
    try:
        return sf.resolve(root, rel, must_exist=must_exist)
    except sf.FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def _running(server: GameServer) -> bool:
    if not server.systemd_unit:
        return False
    props = server_ops._systemctl_props(server.systemd_unit, ("ActiveState", "MainPID"))
    return props.get("ActiveState") == "active" and int(props.get("MainPID") or 0) > 0


def _secrets_ok(perms: set[str], reauthed: bool = False) -> bool:
    """Secrets in the clear: the permission, and the password re-entered in the last 5 minutes."""
    return "files.secrets" in perms and reauthed


def _audit(session: Session, actor: User, server: GameServer, action: str, path: str, **meta) -> None:
    record_audit(session, actor=actor, category="files", action=action, target_type="file",
                 target_id=path[:120], target_label=path[-200:], server_id=server.id, meta=meta or None)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Файл не текстовый (не UTF-8) — его можно только скачать")


# Jars in these top-level folders belong to the «Моды и плагины» section, which knows
# what a plugin or mod is, keeps a staging area and applies them safely.
_JAR_FOLDERS = {"mods", "plugins"}


def _jar_guard(server: GameServer, root: Path, target: Path, *, for_upload: bool = False) -> Path:
    """Jars of mods and plugins are not handled here at all; any other jar (the server
    core, a library) only while the server is stopped — a running JVM reading a jar that
    is replaced under it fails later, out of the blue."""
    if target.suffix.lower() != ".jar":
        return target
    rel = sf.rel_of(root, target)
    if rel.split("/", 1)[0] in _JAR_FOLDERS:
        raise HTTPException(status_code=409, detail="Моды и плагины загружаются, заменяются и удаляются в разделе "
                                                    "«Моды и плагины» — там они проверяются и применяются без поломок. "
                                                    "Их настройки можно править здесь.")
    if _running(server):
        raise HTTPException(status_code=409, detail="Сервер запущен: jar-файлы меняются только на остановленном сервере")
    return target


# ── A partner's server: through its VoidRpPerms (services/remote_file_store.py) ──

def _remote(session: Session, server: GameServer) -> bool:
    """True for a server whose files go through its plugin; refuses when the module is off."""
    if not rfs.is_remote(server):
        return False
    try:
        rfs.require_module(session, server)
    except RemoteFileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return True


def _rel(rel: str | None) -> str:
    try:
        return rfs.norm(rel)
    except RemoteFileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def _remote_jar_guard(rel: str) -> None:
    """On a partner's server every jar goes through «Моды и плагины» (it cannot be stopped from here)."""
    if rel.lower().endswith(".jar"):
        raise HTTPException(status_code=409, detail="Jar-файлы на внешнем сервере загружаются, выключаются и удаляются "
                                                    "в разделе «Моды и плагины». Их настройки можно править здесь.")


class _RemoteCall:
    """Turns the plugin's refusals and silence into the admin's HTTP errors."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if isinstance(exc, RemoteFileError):
            raise HTTPException(status_code=exc.status, detail=str(exc))
        return False


# ── Reading ──────────────────────────────────────────────────────────────────

@router.get("/list")
def list_folder(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    path: str = Query(default=""),
) -> dict:
    if _remote(session, server):
        rel = _rel(path)
        with _RemoteCall():
            entries = rfs.listing(server, rel)
        return {"server": server.slug, "root": server.slug, "path": rel, "parent": rfs.parent_of(rel),
                "entries": entries, "running": True, "remote": True}
    root = _root(server)
    folder = _path(root, path)
    try:
        entries = sf.listing(root, folder)
    except sf.FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    rel = sf.rel_of(root, folder)
    return {
        "server": server.slug,
        "root": root.name,
        "path": rel,
        "parent": None if not rel else rel.rsplit("/", 1)[0] if "/" in rel else "",
        "entries": entries,
        "running": _running(server),
    }


@router.get("/read")
def read_file(
    server: Annotated[GameServer, Depends(resolve_server)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    reauthed: Annotated[bool, Depends(reauth_is_fresh)],
    session: Annotated[Session, Depends(get_db_session)],
    path: str = Query(...),
) -> dict:
    if _remote(session, server):
        return _remote_read(server, perms, reauthed, _rel(path))
    root = _root(server)
    target = _path(root, path)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Это папка")
    if sf.is_secret_file(target) and not _secrets_ok(perms, reauthed):
        if "files.secrets" in perms:
            raise HTTPException(status_code=403, detail="reauth_required")
        raise HTTPException(status_code=403, detail="Этот файл — секрет; нужно право «Файлы: видеть пароли и секреты»")
    size = target.stat().st_size
    if size > sf.EDIT_LIMIT or not sf.is_text(target):
        raise HTTPException(status_code=415, detail="Файл не текстовый или больше 2 МБ — его можно только скачать")
    text = _read_text(target)
    masked = 0
    shown = text
    if not _secrets_ok(perms, reauthed):
        shown, masked = sf.mask(text)
    return {
        # With the permission but no fresh password: masked, the site offers «показать».
        "secrets_locked": bool(masked) and "files.secrets" in perms,
        "path": sf.rel_of(root, target),
        "content": shown,
        "etag": sf.etag(text),
        "size": size,
        "mtime": target.stat().st_mtime,
        "language": sf.LANG.get(target.suffix.lower(), "text"),
        "masked": masked,
        "running": _running(server),
    }


def _remote_read(server: GameServer, perms: set[str], reauthed: bool, rel: str) -> dict:
    from pathlib import PurePosixPath

    if sf.is_secret_file(PurePosixPath(rel)) and not _secrets_ok(perms, reauthed):
        if "files.secrets" in perms:
            raise HTTPException(status_code=403, detail="reauth_required")
        raise HTTPException(status_code=403, detail="Этот файл — секрет; нужно право «Файлы: видеть пароли и секреты»")
    with _RemoteCall():
        info = rfs.stat(server, rel)
        if info is None:
            raise HTTPException(status_code=404, detail="Файл или папка не найдены")
        if info["type"] == "dir":
            raise HTTPException(status_code=400, detail="Это папка")
        if (info["size"] or 0) > sf.EDIT_LIMIT:
            raise HTTPException(status_code=415, detail="Файл больше 2 МБ — его можно только скачать")
        text, size, mtime = rfs.read_text(server, rel)
    masked = 0
    shown = text
    if not _secrets_ok(perms, reauthed):
        shown, masked = sf.mask(text)
    return {
        "secrets_locked": bool(masked) and "files.secrets" in perms,
        "path": rel, "content": shown, "etag": sf.etag(text), "size": size, "mtime": mtime,
        "language": sf.LANG.get(PurePosixPath(rel).suffix.lower(), "text"),
        "masked": masked, "running": True, "remote": True,
    }


@router.get("/download")
def download(
    server: Annotated[GameServer, Depends(resolve_server)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    reauthed: Annotated[bool, Depends(reauth_is_fresh)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
    path: str = Query(...),
):
    if _remote(session, server):
        from pathlib import PurePosixPath

        rel = _rel(path)
        secrets = _secrets_ok(perms, reauthed)
        with _RemoteCall():
            info = rfs.stat(server, rel) if rel else {"type": "dir"}
            if info is None:
                raise HTTPException(status_code=404, detail="Файл или папка не найдены")
            if info["type"] == "file":
                if sf.is_secret_file(PurePosixPath(rel)) and not secrets:
                    raise HTTPException(status_code=403, detail="Этот файл — секрет; нужно право «Файлы: видеть пароли и секреты»")
                data = rfs.read_bytes(server, rel)
                _audit(session, actor, server, "download", rel, size=len(data), remote=True)
                name = PurePosixPath(rel).name
                return StreamingResponse(io.BytesIO(data), media_type="application/octet-stream",
                                         headers={"Content-Disposition": f'attachment; filename="{name}"'})
            data, count, total = rfs.zip_folder(server, rel, secrets)
        _audit(session, actor, server, "download_zip", rel or "/", files=count, size=total, remote=True)
        name = (PurePosixPath(rel).name or server.slug) + ".zip"
        return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})
    root = _root(server)
    target = _path(root, path)
    rel = sf.rel_of(root, target)
    secrets = _secrets_ok(perms, reauthed)
    if target.is_file():
        if sf.is_secret_file(target) and not secrets:
            raise HTTPException(status_code=403, detail="Этот файл — секрет; нужно право «Файлы: видеть пароли и секреты»")
        _audit(session, actor, server, "download", rel, size=target.stat().st_size)
        return FileResponse(target, filename=target.name)
    # A folder, as a zip — within a size limit, secrets left out without the permission.
    files, total = [], 0
    for dirpath, _dirs, names in os.walk(target):
        for name in names:
            p = Path(dirpath) / name
            if not secrets and sf.is_secret_file(p):
                continue
            try:
                real = sf.resolve(root, sf.rel_of(root, p))
                total += real.stat().st_size
            except (sf.FileError, OSError):
                continue
            if total > ZIP_LIMIT:
                raise HTTPException(status_code=413, detail="Папка больше 500 МБ — скачайте её частями (например, через бэкап)")
            files.append(real)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, str(p.relative_to(target)))
    buf.seek(0)
    _audit(session, actor, server, "download_zip", rel or "/", files=len(files), size=total)
    name = (target.name or server.slug) + ".zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── Editing ──────────────────────────────────────────────────────────────────

class WriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str
    # The etag the editor loaded the file with; a mismatch means someone changed it meanwhile.
    etag: str | None = None
    create: bool = False
    note: str | None = Field(default=None, max_length=256)


def _save(session: Session, actor: User, server: GameServer, root: Path, target: Path,
          new_text: str, before: str | None, note: str | None) -> dict:
    if len(new_text.encode("utf-8")) > sf.EDIT_LIMIT:
        raise HTTPException(status_code=413, detail="Больше 2 МБ — такой файл через редактор не сохранить")
    try:
        sf.check_syntax(target, new_text)
    except sf.FileError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    added, removed = sf.diff_counts(before, new_text)
    rel = sf.rel_of(root, target)
    sf.write_atomic(target, new_text.encode("utf-8"))
    rev = FileRevision(server_id=server.id, path=rel, content_before=before, content_after=new_text,
                       lines_added=added, lines_removed=removed, author=actor.site_login, note=note)
    session.add(rev)
    session.commit()
    # Keep the last KEEP_REVISIONS of each file.
    old = (session.query(FileRevision.id)
           .filter(FileRevision.server_id == server.id, FileRevision.path == rel)
           .order_by(FileRevision.created_at.desc()).offset(KEEP_REVISIONS).all())
    if old:
        session.query(FileRevision).filter(FileRevision.id.in_([i for (i,) in old])).delete(synchronize_session=False)
        session.commit()
    _audit(session, actor, server, "edit" if before is not None else "create", rel,
           lines_added=added, lines_removed=removed, note=note)
    return {"path": rel, "etag": sf.etag(new_text), "lines_added": added, "lines_removed": removed,
            "revision": str(rev.id), "running": _running(server)}


def _remote_save(session: Session, actor: User, server: GameServer, rel: str,
                 new_text: str, before: str | None, note: str | None, *, create: bool = False) -> dict:
    from pathlib import PurePosixPath

    if len(new_text.encode("utf-8")) > sf.EDIT_LIMIT:
        raise HTTPException(status_code=413, detail="Больше 2 МБ — такой файл через редактор не сохранить")
    try:
        sf.check_syntax(PurePosixPath(rel), new_text)
    except sf.FileError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    added, removed = sf.diff_counts(before, new_text)
    with _RemoteCall():
        rfs.write_text(server, rel, new_text, create=create)
    rev = FileRevision(server_id=server.id, path=rel, content_before=before, content_after=new_text,
                       lines_added=added, lines_removed=removed, author=actor.site_login, note=note)
    session.add(rev)
    session.commit()
    old = (session.query(FileRevision.id)
           .filter(FileRevision.server_id == server.id, FileRevision.path == rel)
           .order_by(FileRevision.created_at.desc()).offset(KEEP_REVISIONS).all())
    if old:
        session.query(FileRevision).filter(FileRevision.id.in_([i for (i,) in old])).delete(synchronize_session=False)
        session.commit()
    _audit(session, actor, server, "edit" if before is not None else "create", rel,
           lines_added=added, lines_removed=removed, note=note, remote=True)
    return {"path": rel, "etag": sf.etag(new_text), "lines_added": added, "lines_removed": removed,
            "revision": str(rev.id), "running": True}


def _remote_write(req: "WriteRequest", server: GameServer, perms: set[str], reauthed: bool,
                  session: Session, actor: User) -> dict:
    from pathlib import PurePosixPath

    rel = _rel(req.path)
    _remote_jar_guard(rel)
    if req.create:
        with _RemoteCall():
            if rfs.stat(server, rel) is not None:
                raise HTTPException(status_code=409, detail="Такой файл уже есть")
        return _remote_save(session, actor, server, rel, req.content, None, req.note, create=True)
    if sf.is_secret_file(PurePosixPath(rel)) and not _secrets_ok(perms, reauthed):
        raise HTTPException(status_code=403, detail="reauth_required" if "files.secrets" in perms
                            else "Этот файл — секрет; нужно право «Файлы: видеть пароли и секреты»")
    with _RemoteCall():
        current = rfs.read_text(server, rel)[0]
    if req.etag and req.etag != sf.etag(current):
        raise HTTPException(status_code=409, detail="Файл изменился, пока он был открыт (сервер или кто-то ещё). "
                                                    "Откройте его заново, чтобы не затереть чужие правки.")
    try:
        new_text = sf.unmask(req.content, current)
    except sf.FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    if new_text == current:
        return {"path": rel, "etag": sf.etag(current), "unchanged": True, "lines_added": 0, "lines_removed": 0, "running": True}
    return _remote_save(session, actor, server, rel, new_text, current, req.note)


@router.put("/write", dependencies=[Depends(require_permission("files.edit"))])
def write_file(
    req: WriteRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    reauthed: Annotated[bool, Depends(reauth_is_fresh)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    if _remote(session, server):
        return _remote_write(req, server, perms, reauthed, session, actor)
    root = _root(server)
    if req.create:
        target = _path(root, req.path, must_exist=False)
        if target.exists():
            raise HTTPException(status_code=409, detail="Такой файл уже есть")
        if not target.parent.is_dir():
            raise HTTPException(status_code=404, detail="Папки для файла нет")
        return _save(session, actor, server, root, target, req.content, None, req.note)
    target = _path(root, req.path)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Это папка")
    if sf.is_secret_file(target) and not _secrets_ok(perms, reauthed):
        raise HTTPException(status_code=403, detail="reauth_required" if "files.secrets" in perms
                            else "Этот файл — секрет; нужно право «Файлы: видеть пароли и секреты»")
    current = _read_text(target)
    if req.etag and req.etag != sf.etag(current):
        raise HTTPException(status_code=409, detail="Файл изменился, пока он был открыт (сервер или кто-то ещё). "
                                                    "Откройте его заново, чтобы не затереть чужие правки.")
    # Masked secrets are always put back (only lines still carrying the mask are touched),
    # so a mask can never overwrite a real password — whoever saved and however they saw it.
    try:
        new_text = sf.unmask(req.content, current)
    except sf.FileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    if new_text == current:
        return {"path": sf.rel_of(root, target), "etag": sf.etag(current), "unchanged": True,
                "lines_added": 0, "lines_removed": 0, "running": _running(server)}
    return _save(session, actor, server, root, target, new_text, current, req.note)


@router.get("/revisions")
def revisions(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    path: str = Query(...),
) -> dict:
    if rfs.is_remote(server):
        rel = _rel(path)
    else:
        root = _root(server)
        rel = sf.rel_of(root, _path(root, path, must_exist=False))
    rows = (session.query(FileRevision).filter(FileRevision.server_id == server.id, FileRevision.path == rel)
            .order_by(FileRevision.created_at.desc()).limit(KEEP_REVISIONS).all())
    return {"items": [
        {"id": str(r.id), "author": r.author, "at": r.created_at.isoformat(), "lines_added": r.lines_added,
         "lines_removed": r.lines_removed, "note": r.note, "created": r.content_before is None}
        for r in rows
    ]}


@router.get("/revisions/{revision_id}")
def revision(
    revision_id: UUID,
    server: Annotated[GameServer, Depends(resolve_server)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    reauthed: Annotated[bool, Depends(reauth_is_fresh)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    r = session.get(FileRevision, revision_id)
    if r is None or r.server_id != server.id:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    before, after = r.content_before, r.content_after
    if not _secrets_ok(perms, reauthed):
        before = sf.mask(before)[0] if before is not None else None
        after = sf.mask(after)[0]
    return {"id": str(r.id), "path": r.path, "author": r.author, "at": r.created_at.isoformat(),
            "before": before, "after": after, "note": r.note}


@router.post("/revisions/{revision_id}/revert", dependencies=[Depends(require_permission("files.edit"))])
def revert(
    revision_id: UUID,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    """Undoes one save: the file goes back to what it was before it (as a new save, so
    the undo can itself be undone)."""
    r = session.get(FileRevision, revision_id)
    if r is None or r.server_id != server.id:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    if r.content_before is None:
        raise HTTPException(status_code=400, detail="Этой правкой файл был создан — вернуть «до» нечего, его можно удалить")
    if _remote(session, server):
        with _RemoteCall():
            current = rfs.read_text(server, r.path)[0]
        when = r.created_at.astimezone().strftime("%d.%m %H:%M")
        return _remote_save(session, actor, server, r.path, r.content_before, current,
                            f"откат правки {r.author or '—'} от {when}")
    root = _root(server)
    target = _path(root, r.path)
    current = _read_text(target)
    when = r.created_at.astimezone().strftime("%d.%m %H:%M")
    return _save(session, actor, server, root, target, r.content_before, current,
                 f"откат правки {r.author or '—'} от {when}")


# ── Files and folders ────────────────────────────────────────────────────────

@router.post("/upload", dependencies=[Depends(require_permission("files.upload"))])
async def upload(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
    path: str = Form(default=""),
    overwrite: bool = Form(default=False),
    files: list[UploadFile] = File(...),
) -> dict:
    if _remote(session, server):
        folder_rel = _rel(path)
        saved = []
        for up in files:
            try:
                name = sf.safe_name(Path(up.filename or "").name)
            except sf.FileError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            rel = f"{folder_rel}/{name}" if folder_rel else name
            _remote_jar_guard(rel)
            data = await up.read(UPLOAD_LIMIT + 1)
            if len(data) > UPLOAD_LIMIT:
                raise HTTPException(status_code=413, detail=f"«{name}» больше 200 МБ")
            from starlette.concurrency import run_in_threadpool

            with _RemoteCall():
                exists = await run_in_threadpool(rfs.stat, server, rel)
                if exists is not None and not overwrite:
                    raise HTTPException(status_code=409, detail=f"«{name}» уже есть — включите замену, если нужно перезаписать")
                await run_in_threadpool(rfs.write_bytes, server, rel, data)
            saved.append({"path": rel, "size": len(data), "redirected": False})
            _audit(session, actor, server, "upload", rel, size=len(data), overwrite=overwrite, remote=True)
        return {"saved": saved, "running": True}
    root = _root(server)
    folder = _path(root, path)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Загружать можно только в папку")
    saved = []
    for up in files:
        try:
            name = sf.safe_name(Path(up.filename or "").name)
        except sf.FileError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        target = _jar_guard(server, root, _path(root, sf.rel_of(root, folder / name), must_exist=False), for_upload=True)
        if target.exists() and not overwrite:
            raise HTTPException(status_code=409, detail=f"«{name}» уже есть — включите замену, если нужно перезаписать")
        data = await up.read(UPLOAD_LIMIT + 1)
        if len(data) > UPLOAD_LIMIT:
            raise HTTPException(status_code=413, detail=f"«{name}» больше 200 МБ")
        sf.write_atomic(target, data)
        rel = sf.rel_of(root, target)
        saved.append({"path": rel, "size": len(data), "redirected": target.parent != folder})
        _audit(session, actor, server, "upload", rel, size=len(data), overwrite=overwrite)
    return {"saved": saved, "running": _running(server)}


class NameRequest(BaseModel):
    path: str = Field(default="", max_length=1024)
    name: str = Field(min_length=1, max_length=255)


@router.post("/mkdir", dependencies=[Depends(require_permission("files.upload"))])
def mkdir(
    req: NameRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    if _remote(session, server):
        try:
            name = sf.safe_name(req.name)
        except sf.FileError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        base = _rel(req.path)
        rel = f"{base}/{name}" if base else name
        with _RemoteCall():
            rfs.mkdir(server, rel)
        _audit(session, actor, server, "mkdir", rel, remote=True)
        return {"path": rel}
    root = _root(server)
    try:
        name = sf.safe_name(req.name)
    except sf.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    parent = _path(root, req.path)
    target = _path(root, sf.rel_of(root, parent / name), must_exist=False)
    if target.exists():
        raise HTTPException(status_code=409, detail="Такое уже есть")
    target.mkdir()
    rel = sf.rel_of(root, target)
    _audit(session, actor, server, "mkdir", rel)
    return {"path": rel}


@router.post("/rename", dependencies=[Depends(require_permission("files.upload"))])
def rename(
    req: NameRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    if _remote(session, server):
        old = _rel(req.path)
        if not old:
            raise HTTPException(status_code=400, detail="Корень папки сервера не переименовать")
        try:
            name = sf.safe_name(req.name)
        except sf.FileError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        parent = rfs.parent_of(old) or ""
        new = f"{parent}/{name}" if parent else name
        _remote_jar_guard(old)
        _remote_jar_guard(new)
        with _RemoteCall():
            rfs.rename(server, old, new)
        session.query(FileRevision).filter(FileRevision.server_id == server.id, FileRevision.path == old).update(
            {FileRevision.path: new}, synchronize_session=False)
        session.commit()
        _audit(session, actor, server, "rename", old, to=new, remote=True)
        return {"path": new}
    root = _root(server)
    source = _path(root, req.path)
    if source == root:
        raise HTTPException(status_code=400, detail="Корень папки сервера не переименовать")
    try:
        name = sf.safe_name(req.name)
    except sf.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _jar_guard(server, root, source)
    target = _path(root, sf.rel_of(root, source.parent / name), must_exist=False)
    _jar_guard(server, root, target)
    if target.exists():
        raise HTTPException(status_code=409, detail="Такое имя уже занято")
    source.rename(target)
    old, new = sf.rel_of(root, source), sf.rel_of(root, target)
    session.query(FileRevision).filter(FileRevision.server_id == server.id, FileRevision.path == old).update(
        {FileRevision.path: new}, synchronize_session=False)
    session.commit()
    _audit(session, actor, server, "rename", old, to=new)
    return {"path": new}


@router.delete("", dependencies=[Depends(require_permission("files.delete"))])
def delete(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
    path: str = Query(...),
) -> dict:
    if _remote(session, server):
        rel = _rel(path)
        if not rel:
            raise HTTPException(status_code=400, detail="Папку сервера целиком удалить нельзя")
        _remote_jar_guard(rel)
        if rel.split("/", 1)[0] in _JAR_FOLDERS and "/" not in rel:
            raise HTTPException(status_code=409, detail="Папки mods и plugins целиком не удаляются")
        with _RemoteCall():
            count = rfs.delete(server, rel)
        _audit(session, actor, server, "delete", rel, files=count, remote=True)
        return {"deleted": rel}
    root = _root(server)
    target = _path(root, path)
    if target == root:
        raise HTTPException(status_code=400, detail="Папку сервера целиком удалить нельзя")
    rel = sf.rel_of(root, target)
    if target.is_dir() and (target / "level.dat").exists() and _running(server):
        raise HTTPException(status_code=409, detail="Это мир запущенного сервера — сначала остановите сервер")
    _jar_guard(server, root, target)
    if target.is_dir() and not target.is_symlink():
        count = sum(len(f) for _, _, f in os.walk(target))
        shutil.rmtree(target)
        _audit(session, actor, server, "delete_dir", rel, files=count)
    else:
        size = target.stat().st_size if target.exists() else 0
        target.unlink()
        _audit(session, actor, server, "delete", rel, size=size)
    return {"deleted": rel}
