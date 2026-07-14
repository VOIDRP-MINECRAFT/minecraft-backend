#!/usr/bin/env python3
"""
Reads WorldGuard regions and writes them as BlueMap markers.
Fetches nation accent colors from the VoidRP API and colors each region
by the nation its owner belongs to.

Run manually or via cron:
  cd /home/mironoouv/minecraft && python3 scripts/update_bluemap_wg_markers.py

BlueMap picks up changes in live/markers.json automatically (no reload needed).
"""

import json
import re
import sys
from pathlib import Path

try:
    import yaml
    import requests
except ImportError:
    print("pip install pyyaml requests", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://api.void-rp.ru/api/v1"

SERVER_ROOT = Path(__file__).parent.parent / "minecraft_server"
WG_WORLDS_DIR = SERVER_ROOT / "plugins/WorldGuard/worlds"
BLUEMAP_MAPS_DIR = SERVER_ROOT / "bluemap/web/maps"
USERCACHE_FILE = SERVER_ROOT / "usercache.json"

# WorldGuard world name → BlueMap map id
WORLD_MAP = {
    "world": "world",
    "DIM-1": "world_the_nether",
    "DIM1": "world_the_end",
    "twilight_forest": "world_twilightforest_twilight_forest",
}

DEFAULT_COLOR = "#7c3aed"
DEFAULT_FILL_OPACITY = 0.15
DEFAULT_LINE_OPACITY = 0.85
DEFAULT_LINE_WIDTH = 2

MARKER_SET_ID = "worldguard-regions"
MARKER_SET_LABEL = "Приваты / Государства"


def hex_to_rgba(hex_color: str, alpha: float) -> dict:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return {"r": r, "g": g, "b": b, "a": alpha}


def load_usercache() -> dict[str, str]:
    """Returns uuid (lowercase, with dashes) → nickname."""
    try:
        entries = json.loads(USERCACHE_FILE.read_text())
        return {e["uuid"].lower(): e["name"] for e in entries}
    except Exception as e:
        print(f"  Warning: could not load usercache: {e}", file=sys.stderr)
        return {}


def fetch_nations() -> list:
    try:
        resp = requests.get(f"{API_BASE}/nations", params={"limit": 200}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"  Warning: could not fetch nations from API: {e}", file=sys.stderr)
        return []


def build_uuid_color_map(nations: list) -> dict[str, str]:
    """Returns lowercase minecraft_nickname → accent_color."""
    result = {}
    for nation in nations:
        color = nation.get("accent_color") or DEFAULT_COLOR
        for member in nation.get("members", []):
            nick = member.get("minecraft_nickname")
            if nick:
                result[nick.lower()] = color
    return result


def build_uuid_nation_map(nations: list) -> dict[str, dict]:
    """Returns lowercase minecraft_nickname → {nation_name, accent_color, slug}."""
    result = {}
    for nation in nations:
        color = nation.get("accent_color") or DEFAULT_COLOR
        name = nation.get("name", "")
        slug = nation.get("slug", "")
        for member in nation.get("members", []):
            nick = member.get("minecraft_nickname")
            if nick:
                result[nick.lower()] = {
                    "name": name,
                    "color": color,
                    "slug": slug,
                    "role": member.get("role", ""),
                }
    return result


def region_to_shape(region: dict) -> tuple[list[dict], dict] | tuple[None, None]:
    """Convert a WG region to (shape_points, center) for BlueMap 5.x.
    Points must be {"x": x, "z": z} dicts, not arrays."""
    rtype = region.get("type")
    if rtype == "cuboid":
        mn = region.get("min", {})
        mx = region.get("max", {})
        x1, z1 = mn.get("x", 0), mn.get("z", 0)
        x2, z2 = mx.get("x", 0), mx.get("z", 0)
        points = [
            {"x": x1, "z": z1},
            {"x": x2, "z": z1},
            {"x": x2, "z": z2},
            {"x": x1, "z": z2},
        ]
        center = {"x": (x1 + x2) / 2, "z": (z1 + z2) / 2}
        return points, center
    elif rtype == "poly2d":
        pts = region.get("points", [])
        points = [{"x": p.get("x", 0), "z": p.get("z", 0)} for p in pts]
        if not points:
            return None, None
        cx = sum(p["x"] for p in points) / len(points)
        cz = sum(p["z"] for p in points) / len(points)
        return points, {"x": cx, "z": cz}
    return None, None


def region_y_range(region: dict) -> tuple[int, int]:
    rtype = region.get("type")
    if rtype == "cuboid":
        mn = region.get("min", {})
        mx = region.get("max", {})
        return mn.get("y", -64), mx.get("y", 320)
    min_y = region.get("min-y", -64)
    max_y = region.get("max-y", 320)
    return min_y, max_y


def build_popup(region_name: str, owners: list[str], members: list[str],
                uuid_nation: dict) -> str:
    """Build HTML popup for a region marker."""
    nation_info = None
    for nick in owners:
        info = uuid_nation.get(nick.lower())
        if info:
            nation_info = info
            break

    owner_str = ", ".join(f"<b>{n}</b>" for n in owners) if owners else "—"
    member_str = ", ".join(members) if members else "—"

    if nation_info:
        color = nation_info["color"]
        slug = nation_info["slug"]
        nation_name = nation_info["name"]
        nation_link = (
            f'<a href="https://void-rp.ru/nation/{slug}" target="_blank" '
            f'onclick="window.open(\'https://void-rp.ru/nation/{slug}\');return false;" '
            f'style="color:#a78bfa;font-size:88%;cursor:pointer">→ Государство на сайте</a>'
        )
        header = (
            f'<strong style="font-size:110%;color:{color}">'
            f'{nation_name}</strong>'
        )
    else:
        header = f'<strong style="font-size:110%">{region_name}</strong>'
        nation_link = ""

    html = (
        f'<div class="regioninfo">'
        f'{header}<br/>'
        f'<span style="font-size:90%;color:#aaa">Владелец: {owner_str}</span><br/>'
        f'<span style="font-size:90%;color:#aaa">Участники: {member_str}</span>'
    )
    if nation_link:
        html += f"<br/>{nation_link}"
    html += "</div>"
    return html


def process_world(wg_world: str, bluemap_map_id: str, uuid_cache: dict,
                  uuid_nation: dict) -> dict:
    """Build marker set dict for one world."""
    regions_file = WG_WORLDS_DIR / wg_world / "regions.yml"
    if not regions_file.exists():
        return {}

    data = yaml.safe_load(regions_file.read_text())
    regions = data.get("regions", {})
    markers = {}

    for region_name, region in regions.items():
        if region.get("type") == "global":
            continue

        shape, center = region_to_shape(region)
        if not shape:
            continue

        min_y, max_y = region_y_range(region)

        # Resolve UUIDs → nicknames
        owner_uuids = region.get("owners", {}).get("unique-ids", []) or []
        member_uuids = region.get("members", {}).get("unique-ids", []) or []
        owner_names = [uuid_cache.get(uid.lower(), uid[:8]) for uid in owner_uuids]
        member_names = [uuid_cache.get(uid.lower(), uid[:8]) for uid in member_uuids]

        # Pick color from nation
        color = DEFAULT_COLOR
        for nick in owner_names:
            info = uuid_nation.get(nick.lower())
            if info:
                color = info["color"]
                break

        popup = build_popup(region_name, owner_names, member_names, uuid_nation)

        markers[region_name] = {
            "type": "shape",
            "label": region_name,
            "detail": popup,
            "position": {"x": center["x"], "y": 64, "z": center["z"]},
            "shape": shape,
            "shapeMinY": min_y,
            "shapeMaxY": max_y,
            "depthTestEnabled": False,
            "lineColor": hex_to_rgba(color, DEFAULT_LINE_OPACITY),
            "fillColor": hex_to_rgba(color, DEFAULT_FILL_OPACITY),
            "lineWidth": DEFAULT_LINE_WIDTH,
            "sorting": 0,
            "listed": True,
            "classes": [],
        }

    return markers


def write_markers(bluemap_map_id: str, markers: dict) -> None:
    # Write to a separate file that BlueMap never touches.
    # The custom JS (wg-regions.js) reads this file and injects markers into the viewer.
    out_file = BLUEMAP_MAPS_DIR / bluemap_map_id / "wg-regions.json"
    if not out_file.parent.exists():
        print(f"  Skipping {bluemap_map_id} — maps dir not found", file=sys.stderr)
        return

    payload = {
        MARKER_SET_ID: {
            "label": MARKER_SET_LABEL,
            "toggleable": True,
            "defaultHidden": False,
            "sorting": 0,
            "markers": markers,
        }
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"  {bluemap_map_id}: wrote {len(markers)} markers → {out_file}")


def main():
    print("Loading usercache...")
    uuid_cache = load_usercache()
    print(f"  {len(uuid_cache)} UUID entries")

    print("Fetching nations from API...")
    nations = fetch_nations()
    print(f"  {len(nations)} nations")

    uuid_nation = build_uuid_nation_map(nations)
    print(f"  {len(uuid_nation)} players mapped to nations")

    print("Processing WorldGuard regions...")
    for wg_world, bluemap_map_id in WORLD_MAP.items():
        markers = process_world(wg_world, bluemap_map_id, uuid_cache, uuid_nation)
        if markers:
            write_markers(bluemap_map_id, markers)
        else:
            print(f"  {wg_world}: no regions")

    print("Done. BlueMap picks up changes automatically.")


if __name__ == "__main__":
    main()
