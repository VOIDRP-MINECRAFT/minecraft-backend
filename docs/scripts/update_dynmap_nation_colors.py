#!/usr/bin/env python3
"""
Updates Dynmap-WorldGuard ownerstyle config so each player's regions
are colored in their nation's accent color.

Run manually or via cron:
  cd /home/mironoouv/minecraft && python3 scripts/update_dynmap_nation_colors.py

After running, reload Dynmap-WorldGuard in-game:
  /dynmap-worldguard reload
or via RCON / restart.
"""

import json
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://api.void-rp.ru/api/v1"
CONFIG_PATH = Path(__file__).parent.parent / "minecraft_server/plugins/Dynmap-WorldGuard/config.yml"

DEFAULT_STYLE = {
    "strokeColor": "#7c3aed",
    "strokeOpacity": 0.75,
    "strokeWeight": 2,
    "fillColor": "#7c3aed",
    "fillOpacity": 0.12,
    "unownedStrokeColor": "#4a5568",
    "unownedFillColor": "#4a5568",
    "unownedFillOpacity": 0.06,
}


def fetch_nations():
    resp = requests.get(f"{API_BASE}/nations", params={"limit": 200}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", data) if isinstance(data, dict) else data


def build_ownerstyle(nations):
    """Return dict of lowercase_nickname -> style for Dynmap-WorldGuard ownerstyle."""
    styles = {}
    for nation in nations:
        color = nation.get("accent_color") or "#7c3aed"
        for member in nation.get("members", []):
            nick = member.get("minecraft_nickname")
            if not nick:
                continue
            styles[nick.lower()] = {
                "strokecolor": color,
                "fillcolor": color,
                "strokeopacity": 0.85,
                "fillopacity": 0.18,
                "strokeweight": 2,
            }
    return styles


def style_to_yaml(style: dict, indent: int = 8) -> str:
    pad = " " * indent
    lines = []
    for k, v in style.items():
        if isinstance(v, str):
            lines.append(f"{pad}{k}: '{v}'")
        else:
            lines.append(f"{pad}{k}: {v}")
    return "\n".join(lines)


def update_config(config_path: Path, ownerstyle: dict):
    text = config_path.read_text(encoding="utf-8")

    # Replace ownerstyle block
    new_block_lines = ["ownerstyle:"]
    for nick, style in sorted(ownerstyle.items()):
        new_block_lines.append(f"  {nick}:")
        new_block_lines.append(style_to_yaml(style, indent=4))
    new_block = "\n".join(new_block_lines)

    # Replace existing ownerstyle section
    text = re.sub(r"^ownerstyle:.*?(?=^\w|\Z)", new_block + "\n", text, flags=re.MULTILINE | re.DOTALL)

    config_path.write_text(text, encoding="utf-8")


def main():
    print("Fetching nations from API...")
    nations = fetch_nations()
    print(f"  Found {len(nations)} nations")

    ownerstyle = build_ownerstyle(nations)
    print(f"  Mapped {len(ownerstyle)} player nicknames to nation colors")

    update_config(CONFIG_PATH, ownerstyle)
    print(f"  Config updated: {CONFIG_PATH}")
    print()
    print("Done. Reload Dynmap-WorldGuard in-game: /dynmap-worldguard reload")


if __name__ == "__main__":
    main()
