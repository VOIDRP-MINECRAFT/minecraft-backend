"""The file manager's ground rules: what of a server's folder can be seen, read, changed.

- **The jail.** Every path is relative to the server's folder and resolved with
  ``realpath`` — ``..``, absolute paths and symlinks that lead outside are refused, so
  nothing beyond the server's own folder is ever touched.
- **Secrets.** Files that are nothing but a secret (``.rcon_password``, keys) are closed
  without ``files.secrets``; in config files the values of password/secret/token keys are
  shown as a mask. Saving a file with a mask left in place puts the real value back, so
  someone without the permission can still edit the rest of the file.
- **Checking.** YAML, JSON, TOML and .properties must parse before they are saved: a
  typo in a config does not reach the server.
- **Writing** is atomic (a temp file renamed over), keeping the file's mode.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
import tomllib
from pathlib import Path

import yaml

MASK = "••••••••"
EDIT_LIMIT = 2 * 1024 * 1024  # text files larger than this are download-only

# Files that are a secret as a whole.
SECRET_FILES = re.compile(r"(^\.rcon_password$|\.(pem|key|p12|jks|keystore)$|^\.env$)", re.I)
# Keys whose values are secrets in yml/properties/toml/json/conf files.
SECRET_KEY = re.compile(r"(password|passwd|secret|token|api[_-]?key|private[_-]?key)", re.I)

TEXT_EXT = {
    ".yml", ".yaml", ".json", ".json5", ".toml", ".properties", ".txt", ".md", ".cfg", ".conf",
    ".ini", ".sh", ".log", ".csv", ".xml", ".html", ".js", ".mcmeta", ".snbt", ".zs", ".lang",
    ".mcfunction", ".sk", ".env", ".list", ".sql", ".kts", ".gradle", ".py",
}
LANG = {".yml": "yaml", ".yaml": "yaml", ".json": "json", ".json5": "json", ".mcmeta": "json",
        ".toml": "toml", ".properties": "properties", ".xml": "xml", ".sh": "shell",
        ".js": "javascript", ".html": "html", ".md": "markdown", ".py": "python"}


class FileError(Exception):
    """What went wrong, in words for the admin panel; ``status`` for the HTTP answer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def root_of(data_dir: str | None) -> Path:
    if not data_dir or not os.path.isdir(data_dir):
        raise FileError("У сервера нет папки на этой машине (data_dir) — файлы недоступны", 409)
    return Path(os.path.realpath(data_dir))


def resolve(root: Path, rel: str | None, *, must_exist: bool = True) -> Path:
    """``rel`` inside ``root``, or FileError. Symlinks are followed and must stay inside."""
    rel = (rel or "").replace("\\", "/").strip()
    if rel.startswith("/") or "\x00" in rel:
        raise FileError("Путь должен быть внутри папки сервера")
    target = root / rel if rel else root
    if must_exist:
        if not os.path.lexists(target):
            raise FileError("Файл или папка не найдены", 404)
        real = Path(os.path.realpath(target))
    else:
        parent = Path(os.path.realpath(target.parent))
        real = parent / target.name
    if real != root and root not in real.parents:
        raise FileError("Путь выходит за пределы папки сервера", 403)
    return real


def rel_of(root: Path, path: Path) -> str:
    return "" if path == root else str(path.relative_to(root)).replace(os.sep, "/")


def is_secret_file(path: Path) -> bool:
    return bool(SECRET_FILES.search(path.name))


def is_text(path: Path, head: bytes | None = None) -> bool:
    if path.suffix.lower() in TEXT_EXT or path.name in ("server.properties", "eula.txt", "ops.json", "Dockerfile"):
        return True
    if head is None:
        try:
            with open(path, "rb") as fh:
                head = fh.read(4096)
        except OSError:
            return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def entry(root: Path, path: Path) -> dict:
    try:
        st = os.lstat(path)
    except OSError:
        return {"name": path.name, "path": rel_of(root, path), "type": "missing"}
    is_link = stat.S_ISLNK(st.st_mode)
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": rel_of(root, path),
        "type": "dir" if is_dir else "file",
        "size": None if is_dir else st.st_size,
        "mtime": st.st_mtime,
        "link": is_link,
        "secret": (not is_dir) and is_secret_file(path),
        "editable": (not is_dir) and st.st_size <= EDIT_LIMIT and is_text(path),
    }


def listing(root: Path, folder: Path, limit: int = 2000) -> list[dict]:
    if not folder.is_dir():
        raise FileError("Это не папка")
    names = sorted(os.listdir(folder), key=lambda n: (not (folder / n).is_dir(), n.lower()))
    return [entry(root, folder / n) for n in names[:limit]]


def etag(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── Secrets inside configs ───────────────────────────────────────────────────

# key: value (yaml/conf), key=value (properties), key = value (toml), "key": "value" (json)
_LINE = re.compile(r'^(\s*"?(?P<key>[A-Za-z0-9_.\-]+)"?\s*(?P<sep>:|=)\s*)(?P<val>.*?)(?P<tail>,?\s*)$')


def _secret_line(line: str) -> re.Match | None:
    m = _LINE.match(line)
    if not m or not SECRET_KEY.search(m.group("key")):
        return None
    val = m.group("val").strip().strip('"').strip("'")
    if not val or val in ("{", "[", "|", ">", "null", "~", '""', "''"):
        return None
    return m


def mask(text: str) -> tuple[str, int]:
    """The text with secret values masked, and how many were."""
    out, n = [], 0
    for line in text.split("\n"):
        m = _secret_line(line)
        if m:
            quote = '"' if m.group("val").strip().startswith('"') else ("'" if m.group("val").strip().startswith("'") else "")
            out.append(f"{m.group(1)}{quote}{MASK}{quote}{m.group('tail')}")
            n += 1
        else:
            out.append(line)
    return "\n".join(out), n


def unmask(new_text: str, original: str) -> str:
    """Puts back the real values of secrets left masked in ``new_text``, matching each
    masked line to the same key (and its n-th occurrence) in the file as it is."""
    originals: dict[str, list[str]] = {}
    for line in original.split("\n"):
        m = _secret_line(line)
        if m:
            originals.setdefault(m.group("key"), []).append(m.group("val"))
    seen: dict[str, int] = {}
    out = []
    for line in new_text.split("\n"):
        m = _LINE.match(line)
        if m and MASK in m.group("val"):
            key = m.group("key")
            i = seen.get(key, 0)
            seen[key] = i + 1
            values = originals.get(key) or []
            if i >= len(values):
                raise FileError(f"В строке «{key}» осталась маска, а настоящего значения нет — впишите значение")
            out.append(f"{m.group(1)}{values[i]}{m.group('tail')}")
        else:
            out.append(line)
    return "\n".join(out)


# ── Checking before saving ───────────────────────────────────────────────────

def check_syntax(path: Path, text: str) -> None:
    ext = path.suffix.lower()
    try:
        if ext in (".yml", ".yaml"):
            list(yaml.safe_load_all(text))
        elif ext in (".json", ".mcmeta"):
            json.loads(text)
        elif ext == ".toml":
            tomllib.loads(text)
        elif ext == ".properties":
            for n, line in enumerate(text.split("\n"), 1):
                s = line.strip()
                if s and not s.startswith(("#", "!")) and "=" not in s and ":" not in s:
                    raise ValueError(f"строка {n}: нет «=» — «{s[:60]}»")
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"строка {mark.line + 1}, столбец {mark.column + 1}: " if mark else ""
        raise FileError(f"YAML не разбирается — {where}{getattr(exc, 'problem', exc)}")
    except json.JSONDecodeError as exc:
        raise FileError(f"JSON не разбирается — строка {exc.lineno}, столбец {exc.colno}: {exc.msg}")
    except tomllib.TOMLDecodeError as exc:
        raise FileError(f"TOML не разбирается — {exc}")
    except ValueError as exc:
        raise FileError(f"Файл не разбирается — {exc}")


def diff_counts(before: str | None, after: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.ndiff((before or "").split("\n"), after.split("\n")):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def write_atomic(path: Path, data: bytes) -> None:
    mode = None
    if path.exists():
        mode = stat.S_IMODE(os.stat(path).st_mode)
    tmp = path.with_name(f".{path.name}.voidrp-tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def safe_name(name: str) -> str:
    name = (name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name or len(name) > 255:
        raise FileError("Недопустимое имя")
    return name
