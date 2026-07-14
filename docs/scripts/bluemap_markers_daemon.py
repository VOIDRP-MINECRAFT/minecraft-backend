#!/usr/bin/env python3
"""
Daemon: watches live/markers.json for changes and immediately re-injects
worldguard-regions from wg-regions.json. Latency ≤ 0.5 s.

Run once in the background:
  nohup python3 scripts/bluemap_markers_daemon.py >> logs/bluemap-markers-daemon.log 2>&1 &
"""

import json
import time
import sys
from pathlib import Path

MAPS_DIR = Path(__file__).parent.parent / "minecraft_server/bluemap/web/maps"
MAP_IDS = [
    "world",
    "world_the_nether",
    "world_the_end",
    "world_twilightforest_twilight_forest",
]
MARKER_SET_ID = "worldguard-regions"
POLL_INTERVAL = 0.5


def merge_one(map_id: str) -> bool:
    markers_file = MAPS_DIR / map_id / "live" / "markers.json"
    wg_file = MAPS_DIR / map_id / "wg-regions.json"
    if not markers_file.exists() or not wg_file.exists():
        return False
    try:
        data = json.loads(markers_file.read_text(encoding="utf-8"))
        if MARKER_SET_ID in data:
            return False  # already present, nothing to do
        wg = json.loads(wg_file.read_text(encoding="utf-8"))
        data.update(wg)
        markers_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"[daemon] {map_id}: re-injected {len(wg.get(MARKER_SET_ID, {}).get('markers', {}))} WG markers", flush=True)
        return True
    except Exception as e:
        print(f"[daemon] {map_id}: error — {e}", file=sys.stderr, flush=True)
        return False


def main():
    print(f"[daemon] started, watching {len(MAP_IDS)} maps every {POLL_INTERVAL}s", flush=True)
    last_mtimes: dict[str, float] = {}

    while True:
        for map_id in MAP_IDS:
            markers_file = MAPS_DIR / map_id / "live" / "markers.json"
            if not markers_file.exists():
                continue
            try:
                mtime = markers_file.stat().st_mtime
            except OSError:
                continue
            prev = last_mtimes.get(map_id)
            if prev != mtime:
                last_mtimes[map_id] = mtime
                if prev is not None:  # skip first check (initial read)
                    merge_one(map_id)
                else:
                    merge_one(map_id)  # also run on startup
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
