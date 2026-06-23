from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from apps.api.app.db import SessionLocal
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.refresh_session import RefreshSession
from apps.api.app.core.security import utc_now
from apps.api.app.utils.normalization import normalize_minecraft_nickname


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import legacy password hashes into VoidRP player_accounts."
    )
    parser.add_argument("--file", required=True, help="Path to JSON or YAML file")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not commit changes")
    parser.add_argument(
        "--default-algo",
        default="custom_pbkdf2_sha256",
        help="Fallback algo if row does not contain legacy_hash_algo",
    )
    parser.add_argument(
        "--enable-legacy",
        action="store_true",
        help="Enable legacy_auth_enabled for every imported row",
    )
    parser.add_argument(
        "--revoke-refresh-sessions",
        action="store_true",
        help="Revoke active refresh sessions for updated users",
    )
    return parser.parse_args()


def load_payload(path: Path):
    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".json":
        return json.loads(text)

    if path.suffix.lower() in {".yml", ".yaml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SystemExit(
                "PyYAML is required for YAML import. Install it or convert the file to JSON."
            ) from exc

        return yaml.safe_load(text)

    raise SystemExit("Unsupported file format. Use .json, .yml or .yaml")


def iter_rows(payload):
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                raise SystemExit("Every list item must be an object")
            yield item
        return

    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("minecraft_nickname", str(key))
                yield row
                continue

            raise SystemExit("Object values must be objects")
        return

    raise SystemExit("Payload must be either a list or an object")


def revoke_active_refresh_sessions(session, user_id):
    rows = session.execute(
        select(RefreshSession).where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
    ).scalars().all()

    now = utc_now()
    for refresh_session in rows:
        refresh_session.revoked_at = now
        refresh_session.last_used_at = now


def main() -> int:
    args = parse_args()
    path = Path(args.file)

    if not path.exists():
        raise SystemExit(f"Input file does not exist: {path}")

    payload = load_payload(path)

    updated = 0
    skipped_missing_player = 0
    skipped_missing_hash = 0
    skipped_invalid_rows = 0

    session = SessionLocal()

    try:
        for row in iter_rows(payload):
            try:
                nickname_value = str(row.get("minecraft_nickname", "")).strip()
                if not nickname_value:
                    raise ValueError("minecraft_nickname is missing")

                _, nickname_normalized = normalize_minecraft_nickname(nickname_value)

                legacy_hash = str(
                    row.get("legacy_password_hash")
                    or row.get("hash")
                    or ""
                ).strip()

                legacy_algo = str(
                    row.get("legacy_hash_algo")
                    or row.get("algo")
                    or args.default_algo
                ).strip()

                if not legacy_hash:
                    print(f"[SKIP:NO_HASH] {nickname_value}")
                    skipped_missing_hash += 1
                    continue

                player_account = session.execute(
                    select(PlayerAccount).where(
                        PlayerAccount.minecraft_nickname_normalized == nickname_normalized
                    )
                ).scalar_one_or_none()

                if player_account is None:
                    print(f"[SKIP:NO_PLAYER] {nickname_value}")
                    skipped_missing_player += 1
                    continue

                player_account.legacy_password_hash = legacy_hash
                player_account.legacy_hash_algo = legacy_algo

                if args.enable_legacy or bool(row.get("legacy_auth_enabled", False)):
                    player_account.legacy_auth_enabled = True

                if args.revoke_refresh_sessions:
                    revoke_active_refresh_sessions(session, player_account.user_id)

                print(
                    f"[OK] {player_account.minecraft_nickname} "
                    f"legacy_enabled={player_account.legacy_auth_enabled} "
                    f"algo={player_account.legacy_hash_algo}"
                )
                updated += 1

            except Exception as exc:
                skipped_invalid_rows += 1
                print(f"[SKIP:INVALID] {row!r} :: {exc}")

        if args.dry_run:
            session.rollback()
            print("\nDRY RUN completed. No DB changes were committed.")
        else:
            session.commit()
            print("\nImport committed successfully.")

        print(
            "\nSummary: "
            f"updated={updated}, "
            f"missing_player={skipped_missing_player}, "
            f"missing_hash={skipped_missing_hash}, "
            f"invalid_rows={skipped_invalid_rows}"
        )
        return 0

    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())