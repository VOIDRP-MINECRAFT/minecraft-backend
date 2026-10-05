"""Publish a build of our plugin or mod for the «Интеграция» page.

    .venv/bin/python -m apps.worker.publish_release voidrp-auth path/to/voidrp-auth-1.2.0-all.jar \\
        --version 1.2.0 --platforms paper,folia --mc 26.2 --changelog "Что изменилось" --recommended

Copies the jar under RELEASES_DIR/<plugin>/<version>/, records its size and sha256. With
--recommended it becomes the build offered first for those Minecraft versions (the previous
recommended one for the same versions steps down).
"""
from __future__ import annotations

import argparse
import os
import sys


from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import releases
from apps.api.app.db import SessionLocal


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
    with open(a.jar, "rb") as fh:
        data = fh.read()
    s = SessionLocal()
    row = releases.record(
        s, plugin=a.plugin, version=a.version, data=data, filename=filename,
        platforms=[p.strip() for p in a.platforms.split(",") if p.strip()],
        mc_versions=[v.strip() for v in a.mc.split(",") if v.strip()],
        changelog=a.changelog, recommended=a.recommended, published_by=a.by,
    )
    s.commit()
    digest = row.sha256
    print(f"published {a.plugin} {a.version} {filename} sha256={digest[:12]}… recommended={row.recommended}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
