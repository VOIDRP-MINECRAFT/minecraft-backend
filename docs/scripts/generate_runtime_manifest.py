#!/usr/bin/env python3
"""
Generate VoidRP runtime-seed manifest.

Reads:  /home/mironoouv/launcher/runtime-seed/
Writes: /home/mironoouv/launcher/manifests/runtime-manifest.win-x64.json

Usage:
    python3 scripts/generate_runtime_manifest.py
    python3 scripts/generate_runtime_manifest.py --seed-root /custom/path --output /custom/out.json
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
from urllib.parse import quote

DEFAULTS = {
    "seed_root":           "/home/mironoouv/launcher/runtime-seed",
    "output":              "/home/mironoouv/launcher/manifests/runtime-manifest.win-x64.json",
    "base_url":            "https://void-rp.ru/launcher/runtime-seed",
    "pack_name":           "VoidRP Runtime Seed",
    "pack_version":        "1.0.0",
    "pack_display_version": "Better MC [NEOFORGE] BMC5 Better MC [NEOFORGE] 1.21.1 v47",
    "launcher_profile_id": "Better MC [NEOFORGE] BMC5 Better MC [NEOFORGE] 1.21.1 v47",
    "neoforge_version":    "21.1.233",
    "fml_version":         "4.0.42",
    "neoform_version":     "20240808.144430",
    "mc_version":          "1.21.1",
    "loader":              "neoforge",
    "java_version":        21,
    "min_launcher_version": "0.1.0",
    "server_host":         "void-rp.ru",
    "server_port":         25565,
}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _encode_url(rel: str) -> str:
    return "/".join(quote(seg, safe="") for seg in rel.split("/"))


class C:
    CYAN  = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    GRAY  = "\033[90m"; RED   = "\033[91m"; RESET  = "\033[0m"


def main():
    ap = argparse.ArgumentParser(description="Generate VoidRP runtime-seed manifest")
    ap.add_argument("--seed-root",            default=DEFAULTS["seed_root"])
    ap.add_argument("--output",               default=DEFAULTS["output"])
    ap.add_argument("--base-url",             default=DEFAULTS["base_url"])
    ap.add_argument("--pack-name",            default=DEFAULTS["pack_name"])
    ap.add_argument("--pack-version",         default=DEFAULTS["pack_version"])
    ap.add_argument("--pack-display-version", default=DEFAULTS["pack_display_version"])
    ap.add_argument("--launcher-profile-id",  default=DEFAULTS["launcher_profile_id"])
    ap.add_argument("--neoforge-version",     default=DEFAULTS["neoforge_version"])
    ap.add_argument("--fml-version",          default=DEFAULTS["fml_version"])
    ap.add_argument("--neoform-version",      default=DEFAULTS["neoform_version"])
    ap.add_argument("--mc-version",           default=DEFAULTS["mc_version"])
    ap.add_argument("--loader",               default=DEFAULTS["loader"])
    ap.add_argument("--java-version",         type=int, default=DEFAULTS["java_version"])
    ap.add_argument("--min-launcher-version", default=DEFAULTS["min_launcher_version"])
    ap.add_argument("--server-host",          default=DEFAULTS["server_host"])
    ap.add_argument("--server-port",          type=int, default=DEFAULTS["server_port"])
    args = ap.parse_args()

    if not os.path.isdir(args.seed_root):
        sys.exit(f"ERROR: seed-root not found: {args.seed_root}")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    files = []
    processed = errors = 0

    for root, dirs, filenames in os.walk(args.seed_root):
        dirs.sort()
        for filename in sorted(filenames):
            full_path = os.path.join(root, filename)
            rel = os.path.relpath(full_path, args.seed_root).replace("\\", "/")
            try:
                sha  = _sha256(full_path)
                size = os.path.getsize(full_path)
                url  = f"{args.base_url}/{_encode_url(rel)}"
                files.append({"path": rel, "size": size, "sha256": sha, "url": url})
                processed += 1
                if processed % 500 == 0:
                    print(f"  ... {processed} файлов обработано")
            except Exception as e:
                errors += 1
                print(f"WARNING: FAILED: {full_path} -- {e}", file=sys.stderr)

    files.sort(key=lambda x: x["path"].lower())

    manifest = {
        "packName":           args.pack_name,
        "packVersion":        args.pack_version,
        "packDisplayVersion": args.pack_display_version,
        "launcherProfileId":  args.launcher_profile_id,
        "neoForgeVersion":    args.neoforge_version,
        "fmlVersion":         args.fml_version,
        "neoFormVersion":     args.neoform_version,
        "buildDateUtc":       datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minecraftVersion":   args.mc_version,
        "loader":             args.loader,
        "javaVersion":        args.java_version,
        "minLauncherVersion": args.min_launcher_version,
        "fullSyncFallback":   True,
        "notes":              "VoidRP launcher manifest for Better MC 5 NeoForge client",
        "server":             {"host": args.server_host, "port": args.server_port},
        "files":              files,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print()
    print(C.CYAN + "===========================================================" + C.RESET)
    print(C.CYAN + f"  {args.output}" + C.RESET)
    print(C.CYAN + "===========================================================" + C.RESET)
    print(f"  Файлов: {processed} обработано, {errors} ошибок")
    print(f"  Всего в манифесте: {len(files)}")
    print()


if __name__ == "__main__":
    main()
