#!/usr/bin/env python3
"""Scan a modpack's mods/ folder and emit a JSON list of mods (id, name,
description, version) for the site's server-guide "Mods" tab.

Reads each .jar's ``META-INF/neoforge.mods.toml`` (or legacy ``mods.toml``), falling
back to ``fabric.mod.json`` and finally the filename. Deduplicates by mod id.

Usage:
  python3 scripts/generate_mods_list.py \
      --mods /home/mironoouv/launcher/pack/mods \
      --out  VOIDRP-SITE/public/mods/voidrp.json
"""
from __future__ import annotations

import argparse
import json
import re
import tomllib
import zipfile
from pathlib import Path

_WS = re.compile(r"\s+")
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = _PLACEHOLDER.sub("", text)
    return _WS.sub(" ", text).strip()


def _from_toml(raw: bytes) -> list[dict]:
    try:
        data = tomllib.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for m in data.get("mods", []) or []:
        mod_id = str(m.get("modId", "")).strip()
        if not mod_id:
            continue
        out.append({
            "id": mod_id,
            "name": clean(m.get("displayName")) or mod_id,
            "description": clean(m.get("description")),
            "version": clean(str(m.get("version", ""))),
        })
    return out


def _from_fabric(raw: bytes) -> list[dict]:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return []
    mod_id = str(data.get("id", "")).strip()
    if not mod_id:
        return []
    return [{
        "id": mod_id,
        "name": clean(data.get("name")) or mod_id,
        "description": clean(data.get("description")),
        "version": clean(str(data.get("version", ""))),
    }]


def extract(jar: Path) -> list[dict]:
    try:
        with zipfile.ZipFile(jar) as z:
            names = set(z.namelist())
            for candidate in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                if candidate in names:
                    mods = _from_toml(z.read(candidate))
                    if mods:
                        return mods
            if "fabric.mod.json" in names:
                mods = _from_fabric(z.read("fabric.mod.json"))
                if mods:
                    return mods
    except zipfile.BadZipFile:
        return []
    # Fallback: derive a readable name from the filename (library / coremod jars).
    stem = jar.stem
    return [{"id": stem.lower(), "name": stem, "description": "", "version": ""}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", required=True, help="path to the pack's mods/ folder")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--translations", help="optional JSON map {mod_id: russian description}")
    args = ap.parse_args()

    translations: dict[str, str] = {}
    if args.translations and Path(args.translations).exists():
        translations = json.loads(Path(args.translations).read_text(encoding="utf-8"))

    mods_dir = Path(args.mods)
    jars = sorted(mods_dir.glob("*.jar"))

    by_id: dict[str, dict] = {}
    for jar in jars:
        for mod in extract(jar):
            by_id.setdefault(mod["id"], mod)

    # Attach Russian descriptions where we have them (keyed by mod id).
    for mod_id, mod in by_id.items():
        ru = clean(translations.get(mod_id))
        if ru:
            mod["description_ru"] = ru

    mods = sorted(by_id.values(), key=lambda m: m["name"].lower())

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(mods, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(jars)} jars -> {len(mods)} mods written to {out_path}")


if __name__ == "__main__":
    main()
