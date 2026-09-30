"""Publish a build of our plugin or mod for the «Интеграция» page.

    .venv/bin/python -m apps.worker.publish_release voidrp-auth path/to/voidrp-auth-1.2.0-all.jar \\
        --version 1.2.0 --platforms paper,folia --mc 26.2 --changelog "Что изменилось" --recommended

Copies the jar under RELEASES_DIR/<plugin>/<version>/, records its size and sha256. With
--recommended it becomes the build offered first for those Minecraft versions (the previous
recommended one for the same versions steps down).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys

from sqlalchemy import select

from apps.api.app.core import integration_catalog as cat
from apps.api.app.db import SessionLocal
from apps.api.app.models.plugin_release import PluginRelease


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin", help="key from core/integration_catalog.py, e.g. voidrp-auth")
    ap.add_argument("jar")
    ap.add_argument("--version", required=True)
    ap.add_argument("--platforms", required=True, help="paper,folia | neoforge,hybrid")
    ap.add_argument("--mc", required=True, help="Minecraft versions, comma-separated")
    ap.add_argument("--changelog", default="")
    ap.add_argument("--filename", help="name the partner saves it as (default: from the catalog)")
    ap.add_argument("--recommended", action="store_true")
    ap.add_argument("--by", default="mironoouv")
    a = ap.parse_args()

    entry = cat.entry(a.plugin)
    if entry is None or entry["kind"] != "ours":
        print(f"unknown plugin key: {a.plugin}", file=sys.stderr)
        return 2
    filename = a.filename or os.path.basename(entry["install_as"])
    target_dir = os.path.join(cat.releases_dir(), a.plugin, a.version)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, filename)
    shutil.copyfile(a.jar, target)
    with open(target, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    mc = [v.strip() for v in a.mc.split(",") if v.strip()]

    s = SessionLocal()
    row = s.scalar(select(PluginRelease).where(
        PluginRelease.plugin == a.plugin, PluginRelease.version == a.version, PluginRelease.filename == filename))
    if row is None:
        row = PluginRelease(plugin=a.plugin, version=a.version, filename=filename)
        s.add(row)
    row.platforms = [p.strip() for p in a.platforms.split(",") if p.strip()]
    row.mc_versions = mc
    row.changelog = a.changelog or None
    row.storage_path = target
    row.size = os.path.getsize(target)
    row.sha256 = digest
    row.published_by = a.by
    if a.recommended:
        for other in s.scalars(select(PluginRelease).where(PluginRelease.plugin == a.plugin,
                                                           PluginRelease.recommended.is_(True))).all():
            if other is not row and set(other.mc_versions or []) & set(mc):
                other.recommended = False
        row.recommended = True
    s.commit()
    print(f"published {a.plugin} {a.version} {filename} sha256={digest[:12]}… recommended={row.recommended}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
