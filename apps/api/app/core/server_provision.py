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
REPO_ROOT = "/home/mironoouv/minecraft"
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
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


# ── Runtime resolution: share per engine version, don't build per server ─────
def runtime_build_script_rel(slug: str) -> str:
    return f"scripts/generate_{slug}_manifests.sh"


def resolve_runtime(existing_servers, slug: str, mc_version: str | None,
                    loader: str | None, java_version: int | None,
                    neoforge_version: str | None) -> dict:
    """Decide a new server's runtime source. Runtime (Java + client libs) depends
    on the ENGINE version (mc+loader+java), not on the server's mods — so if any
    existing server runs the same engine, reuse its runtime URLs. Otherwise it's
    a brand-new engine: point at per-server runtime files and flag that a runtime
    build script is needed (scaffolded on create). Never fabricates a runtime."""
    donor = next(
        (
            s for s in existing_servers
            if s.mc_version == mc_version
            and (s.loader or "") == (loader or "")
            and s.java_version == java_version
            and (getattr(s, "runtime_manifest_url", None) or getattr(s, "runtime_seed_url", None))
        ),
        None,
    )
    if donor is not None:
        return {
            "runtime_seed_url": donor.runtime_seed_url or "",
            "runtime_manifest_url": donor.runtime_manifest_url or "",
            "manifest_build_script": "",  # standard pack generator; runtime reused
            "runtime_source": donor.slug,
            "runtime_needs_build": False,
        }
    name = launcher_folder_name(slug, neoforge_version, mc_version)
    return {
        "runtime_seed_url": f"{PUBLIC_LAUNCHER_BASE}/{name}/manifests/runtime-seed.json",
        "runtime_manifest_url": f"{PUBLIC_LAUNCHER_BASE}/{name}/manifests/runtime-manifest.win-x64.json",
        "manifest_build_script": runtime_build_script_rel(slug),
        "runtime_source": None,
        "runtime_needs_build": True,
    }


_RUNTIME_SCRIPT_TEMPLATE = """#!/usr/bin/env bash
# Автосгенерировано при создании сервера "@@SLUG@@" (новое ядро @@MC@@ / @@LOADER@@).
# Собирает пак-манифест И рантайм-манифест этого сервера (как generate_abyss_manifests.sh).
#
# ПЕРЕД первым запуском:
#   1) наполни  @@SERVER@@/runtime-seed  реальными файлами (java/ libraries/ versions/ assets/)
#      — проще всего скопировать из сервера на таком же ядре и заменить версии.
#   2) проверь FML и NEOFORM ниже (помечены TODO) — для нового ядра их надо задать точно.
# Потом кнопка «Пересобрать манифест» на вкладке Моды (или запуск этого файла) соберёт всё.
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER=@@SERVER@@
BASE_URL=@@BASE_URL@@
MC_VERSION=@@MC@@
NEOFORGE=@@NEOFORGE@@
PROFILE_ID=@@PROFILE_ID@@
FML=@@FML@@            # TODO: FML-версия для этого ядра
NEOFORM=@@NEOFORM@@    # TODO: neoform-версия для этого ядра
JAVA=@@JAVA@@
HOST=@@HOST@@
PORT=@@PORT@@
VENV_PY=/home/mironoouv/minecraft/minecraft_backend/.venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=python3

echo "── Пак-манифест ──────────────────────────────────────────────"
"$VENV_PY" "$SCRIPTS_DIR/generate_launcher_manifest.py" \\
  --pack-root "$SERVER/pack" \\
  --output "$SERVER/manifests/@@SLUG@@.json" \\
  --base-url "$BASE_URL/pack" \\
  --pack-name "@@NAME@@" \\
  --pack-version "${PACK_VERSION:-1.0.0}" \\
  --pack-display-version "@@NAME@@ $MC_VERSION" \\
  --mc-version "$MC_VERSION" \\
  --neoforge-version "$NEOFORGE" \\
  --launcher-profile-id "$PROFILE_ID" \\
  --fml-version "$FML" \\
  --neoform-version "$NEOFORM" \\
  --java-version "$JAVA" \\
  --server-host "$HOST" \\
  --server-port "$PORT" \\
  --overrides-slug @@SLUG@@

echo "── Рантайм-манифест (Java @@JAVA@@ + клиентские файлы) ─────────"
python3 "$SCRIPTS_DIR/generate_runtime_manifest.py" \\
  --seed-root "$SERVER/runtime-seed" \\
  --output "$SERVER/manifests/runtime-manifest.win-x64.json" \\
  --base-url "$BASE_URL/runtime-seed" \\
  --pack-name "@@NAME@@ Runtime Seed" \\
  --pack-display-version "@@NAME@@ $MC_VERSION" \\
  --launcher-profile-id "$PROFILE_ID" \\
  --neoforge-version "$NEOFORGE" \\
  --fml-version "$FML" \\
  --neoform-version "$NEOFORM" \\
  --mc-version "$MC_VERSION" \\
  --java-version "$JAVA" \\
  --server-host "$HOST" \\
  --server-port "$PORT"

cat > "$SERVER/manifests/runtime-seed.json" <<EOF
{ "manifestUrl": "$BASE_URL/manifests/runtime-manifest.win-x64.json" }
EOF
echo "Готово."
"""


def write_runtime_build_script(slug: str, *, name: str, mc_version: str | None,
                               loader: str | None, neoforge_version: str | None,
                               java_version: int | None, port: int | None) -> str:
    """Scaffold scripts/generate_<slug>_manifests.sh for a brand-new engine, so
    the admin doesn't hand-write it. Filled with what the DB knows (paths +
    versions); FML/neoform left as TODO (engine-specific, must be set once).
    Never overwrites an existing file. Returns the repo-relative path."""
    rel = runtime_build_script_rel(slug)
    path = os.path.join(REPO_ROOT, rel)
    folder = launcher_folder_name(slug, neoforge_version, mc_version)
    nf = neoforge_version or (mc_version or "")
    subs = {
        "@@SLUG@@": slug,
        "@@NAME@@": (name or slug).replace('"', "'"),
        "@@SERVER@@": f"{LAUNCHER_ROOT}/{folder}",
        "@@BASE_URL@@": f"{PUBLIC_LAUNCHER_BASE}/{folder}",
        "@@MC@@": mc_version or "",
        "@@LOADER@@": loader or "neoforge",
        "@@NEOFORGE@@": nf,
        "@@PROFILE_ID@@": f"{loader or 'neoforge'}-{nf}",
        "@@FML@@": "0.0.0",
        "@@NEOFORM@@": mc_version or "",
        "@@JAVA@@": str(java_version or 21),
        "@@HOST@@": "void-rp.ru",
        "@@PORT@@": str(port or 25565),
    }
    if not os.path.exists(path):
        content = _RUNTIME_SCRIPT_TEMPLATE
        for k, v in subs.items():
            content = content.replace(k, v)
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(path, 0o755)
    return rel


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
