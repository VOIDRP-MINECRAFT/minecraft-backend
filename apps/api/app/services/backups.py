"""What the admin panel's backups and the backup worker agree on: where archives live
and what of a server counts as its worlds."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# On /home — another physical disk than /mnt/ssd, where the servers are: a backup next to
# the data survives our own mistakes but not the drive dying.
BACKUP_ROOT = Path(os.environ.get("VOIDRP_BACKUP_ROOT", "/home/mironoouv/backups/servers"))

# Leave at least this much free on the backup disk; a backup that would go below it is
# refused rather than started.
MIN_FREE_BYTES = 20 * 1024**3


def archive_dir(slug: str) -> Path:
    return BACKUP_ROOT / slug


def world_folders(data_dir: str | os.PathLike) -> list[str]:
    """The server's world folders: every top-level folder with a level.dat."""
    root = Path(data_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "level.dat").is_file())


def disk_usage(path: Path) -> dict[str, int] | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return None
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def within_backup_root(path: str | os.PathLike) -> bool:
    """Whether a path is inside the backup folder — the only place anything is ever deleted."""
    try:
        return Path(path).resolve().is_relative_to(BACKUP_ROOT.resolve())
    except (OSError, ValueError):
        return False
