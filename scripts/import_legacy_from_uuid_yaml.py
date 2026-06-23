from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import yaml  # type: ignore
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it with: pip install pyyaml"
    ) from exc

from sqlalchemy import select

from apps.api.app.db import SessionLocal
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.refresh_session import RefreshSession
from apps.api.app.core.security import utc_now


DEFAULT_ALGO = "custom_pbkdf2_sha256"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import legacy hashes from old players.yml (offline_uuid -> hash)"
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to old players.yml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matches but do not commit DB changes",
    )
    parser.add_argument(
        "--enable-legacy",
        action="store_true",
        help="Set legacy_auth_enabled=true for matched players",
    )
    parser.add_argument(
        "--revoke-refresh-sessions",
        action="store_true",
        help="Revoke active refresh sessions for matched users",
    )
    parser.add_argument(
        "--algo",
        default=DEFAULT_ALGO,
        help=f"Value for legacy_hash_algo (default: {DEFAULT_ALGO})",
    )
    return parser.parse_args()


def java_name_uuid_from_bytes(data: bytes) -> uuid.UUID:
    """
    Python equivalent of Java UUID.nameUUIDFromBytes(bytes).
    Java uses MD5, then sets version=3 and RFC4122 variant.
    """
    md5_bytes = bytearray(hashlib.md5(data).digest())
    md5_bytes[6] &= 0x0F
    md5_bytes[6] |= 0x30  # version 3
    md5_bytes[8] &= 0x3F
    md5_bytes[8] |= 0x80  # RFC 4122 variant
    return uuid.UUID(bytes=bytes(md5_bytes))


def offline_uuid_for_nickname(nickname: str) -> str:
    seed = f"OfflinePlayer:{nickname}".encode("utf-8")
    return str(java_name_uuid_from_bytes(seed))


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


def load_players_yaml(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise SystemExit("players.yml must contain a top-level mapping")

    result: dict[str, str] = {}

    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not isinstance(value, dict):
            continue

        hash_value = value.get("hash")
        if not isinstance(hash_value, str) or not hash_value.strip():
            continue

        result[key.strip().lower()] = hash_value.strip()

    return result


def main() -> int:
    args = parse_args()
    input_path = Path(args.file)

    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    uuid_to_hash = load_players_yaml(input_path)

    if not uuid_to_hash:
        raise SystemExit("No valid uuid->hash entries found in input file")

    session = SessionLocal()

    matched = 0
    unmatched = 0
    updated = 0

    try:
        player_accounts = session.execute(
            select(PlayerAccount).order_by(PlayerAccount.minecraft_nickname.asc())
        ).scalars().all()

        if not player_accounts:
            raise SystemExit("No player_accounts found in DB")

        for player_account in player_accounts:
            nickname = player_account.minecraft_nickname
            candidate_uuid = offline_uuid_for_nickname(nickname).lower()
            legacy_hash = uuid_to_hash.get(candidate_uuid)

            if not legacy_hash:
                unmatched += 1
                print(f"[MISS] {nickname} -> {candidate_uuid}")
                continue

            matched += 1
            print(f"[MATCH] {nickname} -> {candidate_uuid}")

            player_account.legacy_password_hash = legacy_hash
            player_account.legacy_hash_algo = args.algo

            if args.enable_legacy:
                player_account.legacy_auth_enabled = True

            if args.revoke_refresh_sessions:
                revoke_active_refresh_sessions(session, player_account.user_id)

            updated += 1

        if args.dry_run:
            session.rollback()
            print("\nDRY RUN completed. No changes committed.")
        else:
            session.commit()
            print("\nImport committed.")

        print(
            "\nSummary: "
            f"db_players={len(player_accounts)}, "
            f"matched={matched}, "
            f"unmatched={unmatched}, "
            f"updated={updated}"
        )

        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())