#!/usr/bin/env python3
"""One-time seed: import the plugin's rewards.yml into the battlepass_rewards table.

Reads the LIVE rewards.yml, parses the `free` / `premium` tracks exactly like the plugin's
SeasonRewards.loadTrack, and upserts a row per (server, season, level, track).

Usage (from the backend venv):
    minecraft_backend/.venv/bin/python scripts/seed_battlepass_rewards.py \
        --rewards /mnt/ssd/minecraft_server/plugins/VoidRpBattlePass/rewards.yml \
        --season 2026-08-31 [--server-slug voidrp] [--replace]
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from apps.api.app.db import SessionLocal  # noqa: E402
from apps.api.app.models.battlepass_reward import BattlePassReward  # noqa: E402
from apps.api.app.models.game_server import GameServer  # noqa: E402


def _norm(entry: dict) -> dict:
    """rewards.yml level-entry → battlepass_rewards column values (mirrors SeasonRewards)."""
    rtype = str(entry.get("type", "MONEY")).lower()
    out: dict = {
        "reward_type": rtype,
        "command": None, "material": None, "item_key": None,
        "count": None, "amount": None, "display_name": None, "icon": None,
    }
    if rtype in ("money", "voidcoin", "exp"):
        # 'exp' is unused in the current season but map it defensively → money
        out["reward_type"] = "money" if rtype == "exp" else rtype
        out["amount"] = int(float(entry.get("amount", 0)))
    elif rtype == "item":
        mat = entry.get("material", "PAPER")
        out["material"] = mat
        out["count"] = int(entry.get("count", 1))
        out["display_name"] = entry.get("displayName", mat)
        out["icon"] = entry.get("icon") or f"minecraft:{str(mat).lower()}"
    elif rtype == "command":
        cmd = entry.get("command", "")
        out["command"] = cmd
        out["display_name"] = entry.get("displayName", "Награда")
        icon = entry.get("icon")
        if not icon:
            for tok in str(cmd).split(" "):
                if ":" in tok and not tok.lstrip("/").startswith("minecraft:give"):
                    icon = tok
                    break
        out["icon"] = icon
        out["item_key"] = icon
    else:
        raise ValueError(f"unknown reward type {rtype!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rewards", default="/mnt/ssd/minecraft_server/plugins/VoidRpBattlePass/rewards.yml")
    ap.add_argument("--season", required=True)
    ap.add_argument("--server-slug", default=None, help="default = the is_default server")
    ap.add_argument("--replace", action="store_true", help="wipe existing rows for this (server, season) first")
    args = ap.parse_args()

    data = yaml.safe_load(Path(args.rewards).read_text(encoding="utf-8")) or {}

    with SessionLocal() as session:
        if args.server_slug:
            server = session.scalar(select(GameServer).where(GameServer.slug == args.server_slug))
        else:
            server = session.scalar(select(GameServer).where(GameServer.is_default.is_(True)))
        if server is None:
            print("server not found", file=sys.stderr)
            return 1

        if args.replace:
            session.execute(
                delete(BattlePassReward).where(
                    BattlePassReward.server_id == server.id,
                    BattlePassReward.season == args.season,
                )
            )

        existing = {
            (r.level, r.track): r
            for r in session.scalars(
                select(BattlePassReward).where(
                    BattlePassReward.server_id == server.id,
                    BattlePassReward.season == args.season,
                )
            )
        }

        n = 0
        for track in ("free", "premium"):
            for level, entry in (data.get(track) or {}).items():
                cols = _norm(entry)
                row = existing.get((int(level), track))
                if row is None:
                    row = BattlePassReward(
                        id=uuid.uuid4(), server_id=server.id, season=args.season,
                        level=int(level), track=track, **cols,
                    )
                    session.add(row)
                else:
                    for k, v in cols.items():
                        setattr(row, k, v)
                n += 1

        session.commit()
        print(f"seeded {n} rows for server={server.slug} season={args.season}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
