"""The file manager's operations on a partner's server, through its VoidRpPerms (modules.files).

Same answers as the local ones in routes/admin_files.py (entries, text with secrets masked,
etag…), so the site does not care where the server runs. Rules that need no disk come from
services/server_files.py; paths are checked here as well as by the plugin.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from apps.api.app.core import remote_files, server_console
from apps.api.app.core.remote_files import RemoteFileError
from apps.api.app.models.game_server import GameServer
from apps.api.app.services import server_files as sf

DOWNLOAD_LIMIT = 100 * 1024 * 1024
ZIP_LIMIT = 50 * 1024 * 1024


def is_remote(server: GameServer) -> bool:
    """A partner's machine (or a server without a folder here): files go through its plugin."""
    return bool(server.is_external) or not server.data_dir


def require_module(session: Session, server: GameServer) -> None:
    if not server_console.has_module(session, server, "files"):
        raise RemoteFileError(
            "Файлы этого сервера недоступны: в плагине VoidRpPerms (0.8.0+) не включён модуль files. "
            "Владелец сервера включает его сам: modules.files: true в plugins/VoidRpPerms/config.yml, затем /voidrp reload.",
            409)


def norm(rel: str | None) -> str:
    """A clean path relative to the server folder, or an error (no .., no absolute paths)."""
    rel = (rel or "").replace("\\", "/").strip().strip("/")
    if "\x00" in rel:
        raise RemoteFileError("Недопустимый путь", 400)
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise RemoteFileError("Путь должен быть внутри папки сервера", 403)
    return "/".join(parts)


def parent_of(rel: str) -> str | None:
    if not rel:
        return None
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _looks_text(name: str) -> bool:
    p = PurePosixPath(name)
    return p.suffix.lower() in sf.TEXT_EXT or p.name in ("server.properties", "eula.txt", "ops.json", "Dockerfile")


def entry(e: dict) -> dict:
    """The plugin's entry in the local file manager's shape."""
    is_dir = bool(e.get("dir"))
    name = e.get("name") or ""
    size = None if is_dir else int(e.get("size") or 0)
    return {
        "name": name,
        "path": e.get("path") or name,
        "type": "dir" if is_dir else "file",
        "size": size,
        "mtime": e.get("mtime"),
        "link": bool(e.get("symlink")),
        "secret": (not is_dir) and sf.is_secret_file(PurePosixPath(name)),
        "editable": (not is_dir) and size is not None and size <= sf.EDIT_LIMIT and _looks_text(name),
    }


def listing(server: GameServer, rel: str) -> list[dict]:
    r = remote_files.call(server, "list", path=rel)
    items = [entry(e) for e in r.get("entries") or []]
    items.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    return items


def stat(server: GameServer, rel: str) -> dict | None:
    r = remote_files.call(server, "stat", path=rel)
    return entry(r["entry"]) if r.get("exists") and r.get("entry") else None


def read_text(server: GameServer, rel: str) -> tuple[str, int, float | None]:
    data, meta = remote_files.read_all(server, rel, limit=sf.EDIT_LIMIT)
    if b"\x00" in data[:4096]:
        raise RemoteFileError("Файл не текстовый — его можно только скачать", 415)
    try:
        return data.decode("utf-8"), int(meta.get("size") or len(data)), meta.get("mtime")
    except UnicodeDecodeError:
        raise RemoteFileError("Файл не текстовый (не UTF-8) — его можно только скачать", 415)


def write_text(server: GameServer, rel: str, text: str, *, create: bool = False) -> None:
    remote_files.write_all(server, rel, text.encode("utf-8"), create=create)


def write_bytes(server: GameServer, rel: str, data: bytes) -> None:
    remote_files.write_all(server, rel, data)


def read_bytes(server: GameServer, rel: str, limit: int = DOWNLOAD_LIMIT) -> bytes:
    return remote_files.read_all(server, rel, limit=limit)[0]


def mkdir(server: GameServer, rel: str) -> None:
    remote_files.call(server, "mkdir", path=rel)


def rename(server: GameServer, rel: str, to: str) -> None:
    remote_files.call(server, "rename", path=rel, to=to)


def delete(server: GameServer, rel: str) -> int:
    return int(remote_files.call(server, "delete", timeout=60.0, path=rel).get("deleted") or 0)


def zip_folder(server: GameServer, rel: str, secrets: bool) -> tuple[bytes, int, int]:
    """A folder as a zip (files read one by one), within ZIP_LIMIT; secrets left out without the right."""
    walk = remote_files.call(server, "walk", timeout=30.0, path=rel, limit=5000)
    files = [f for f in walk.get("files") or [] if secrets or not sf.is_secret_file(PurePosixPath(f["path"]))]
    total = sum(int(f.get("size") or 0) for f in files)
    if total > ZIP_LIMIT or walk.get("truncated"):
        raise RemoteFileError("Папка больше 50 МБ — с внешнего сервера скачивайте её частями", 413)
    buf = io.BytesIO()
    prefix = (rel + "/") if rel else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            data = read_bytes(server, f["path"], limit=ZIP_LIMIT)
            zf.writestr(f["path"][len(prefix):] if f["path"].startswith(prefix) else f["path"], data)
    return buf.getvalue(), len(files), total
