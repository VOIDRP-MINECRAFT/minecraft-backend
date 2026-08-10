"""Directory + path provisioning for a newly created game server.

When an admin creates a server, we derive sensible defaults for its modpack /
manifest paths and its monitoring config from the slug + core version, and
physically create the on-disk folder skeleton — so the admin doesn't hand-type
paths (and can't fat-finger a directory into the wrong place). Every derived
field stays editable afterwards; these are just defaults filled when a field is
left blank.

Layout mirrors the existing servers:
  * launcher/manifest files (current disk):  /home/mironoouv/launcher/v<major>-<slug>/{pack,manifests,runtime-seed}
  * server data (nvme, next to the others):  /mnt/ssd/<slug>/mods

Folder creation is confined to those two roots — a derived/overridden path that
resolves elsewhere is refused rather than created.
"""
from __future__ import annotations

import os
import re

LAUNCHER_ROOT = "/home/mironoouv/launcher"
NVME_ROOT = "/mnt/ssd"
PUBLIC_LAUNCHER_BASE = "https://void-rp.ru/launcher"
# /home/mironoouv/launcher is a symlink → /var/www/void-rp/launcher, so the
# containment check must compare *resolved* paths on both sides.
_ALLOWED_ROOTS = (LAUNCHER_ROOT, NVME_ROOT)


class ServerProvisionError(RuntimeError):
    pass


def _core_major(neoforge_version: str | None, mc_version: str | None) -> str:
    """Leading number of the loader core version (fallback MC version).
    NeoForge 26.2.0.8-beta → '26', 21.1.233 → '21', MC 1.21.1 → '1'."""
    for v in (neoforge_version, mc_version):
        if v:
            m = re.match(r"\s*(\d+)", str(v))
            if m:
                return m.group(1)
    return "1"


def launcher_folder_name(slug: str, neoforge_version: str | None, mc_version: str | None) -> str:
    return f"v{_core_major(neoforge_version, mc_version)}-{slug}"


def suggested_fields(slug: str, neoforge_version: str | None = None,
                     mc_version: str | None = None) -> dict:
    """Default modpack + monitoring fields for a new server. Runtime URLs are
    left blank on purpose (blank → launcher-global runtime defaults, the safe
    choice for a standard server; the runtime-seed dir is still created so a
    custom runtime can be added later). log_path blank → auto <data_dir>/logs/latest.log.
    rcon_port is NOT set here (the route picks a free one from the DB)."""
    name = launcher_folder_name(slug, neoforge_version, mc_version)
    return {
        "pack_root": f"{LAUNCHER_ROOT}/{name}/pack",
        "pack_base_url": f"{PUBLIC_LAUNCHER_BASE}/{name}/pack",
        "manifest_url": f"{PUBLIC_LAUNCHER_BASE}/{name}/manifests/{slug}.json",
        "runtime_seed_url": "",
        "runtime_manifest_url": "",
        "data_dir": f"{NVME_ROOT}/{slug}",
        "systemd_unit": f"{slug}.service",
        "rcon_host": "127.0.0.1",
        "log_path": "",
    }


def _is_under_allowed_root(path: str) -> bool:
    real = os.path.realpath(path)
    for root in _ALLOWED_ROOTS:
        rr = os.path.realpath(root)
        if real == rr or real.startswith(rr + os.sep):
            return True
    return False


def provision_dirs(pack_root: str | None, data_dir: str | None) -> list[str]:
    """Create the folder skeleton for a server. Idempotent (exist_ok). Refuses
    any target outside the launcher/nvme roots. Returns the dirs ensured."""
    targets: list[str] = []
    if pack_root:
        base = os.path.dirname(pack_root)
        targets += [
            os.path.join(pack_root, "mods"),
            os.path.join(base, "manifests"),
            os.path.join(base, "runtime-seed"),
        ]
    if data_dir:
        targets.append(os.path.join(data_dir, "mods"))

    ensured: list[str] = []
    for t in targets:
        if not _is_under_allowed_root(t):
            raise ServerProvisionError(
                f"Отказ создавать папку вне разрешённых корней ({LAUNCHER_ROOT}, {NVME_ROOT}): {t}"
            )
        try:
            os.makedirs(t, exist_ok=True)
        except OSError as exc:
            raise ServerProvisionError(f"Не удалось создать папку {t}: {exc}")
        ensured.append(t)
    return ensured
