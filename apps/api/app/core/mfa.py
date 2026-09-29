"""2FA for the admin panel: codes from any authenticator app (TOTP, RFC 6238 — Google
Authenticator, Яндекс Ключ, Aegis, Authy, Microsoft Authenticator, 1Password, Bitwarden…),
codes sent by our Telegram bot, and one-time backup codes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from apps.api.app.config import get_settings

MFA_TTL = timedelta(hours=12)        # a device stays unlocked for the admin panel this long
REAUTH_TTL = timedelta(minutes=5)    # after the password is re-entered, dangerous actions pass
TELEGRAM_CODE_TTL = timedelta(minutes=5)
MAX_FAILURES = 5                     # wrong codes on one device before it is signed out
BACKUP_CODES = 10
ISSUER = "VoidRP"
_STEP = 30
_DIGITS = 6


def _fernet() -> Fernet:
    s = get_settings()
    raw = getattr(s, "mfa_encryption_key", "") or ""
    key = raw.encode() if raw else base64.urlsafe_b64encode(
        hashlib.sha256(("voidrp-mfa:" + s.jwt_secret_key).encode()).digest())
    return Fernet(key)


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


# ── TOTP ─────────────────────────────────────────────────────────────────────

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** _DIGITS).zfill(_DIGITS)


def verify_totp(secret_b32: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """The time step the code matches (±1 step for clock drift), or None. A step already
    used (``last_step``) is refused so a code cannot be replayed."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != _DIGITS:
        return None
    step = int((now if now is not None else time.time()) // _STEP)
    for s in (step, step - 1, step + 1):
        if last_step is not None and s <= last_step:
            continue
        if hmac.compare_digest(_hotp(secret_b32, s), code):
            return s
    return None


def otpauth_uri(secret_b32: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={_DIGITS}&period={_STEP}"


# ── one-time codes (backup, Telegram) ────────────────────────────────────────

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i


def _hash(code: str) -> str:
    pepper = get_settings().jwt_secret_key
    return hashlib.sha256(f"{pepper}:{code}".encode()).hexdigest()


def new_backup_codes() -> tuple[list[str], list[str]]:
    """(codes to show once, their hashes to store)."""
    codes = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) + "-" + "".join(secrets.choice(_ALPHABET) for _ in range(4))
             for _ in range(BACKUP_CODES)]
    return codes, [_hash(c) for c in codes]


def use_backup_code(hashes: list[str], code: str) -> list[str] | None:
    """The remaining hashes if ``code`` is one of them (it is used up), else None."""
    norm = (code or "").strip().lower().replace(" ", "")
    if len(norm) == 8:
        norm = norm[:4] + "-" + norm[4:]
    h = _hash(norm)
    if h not in (hashes or []):
        return None
    return [x for x in hashes if x != h]


def new_numeric_code() -> tuple[str, str]:
    code = str(secrets.randbelow(10 ** _DIGITS)).zfill(_DIGITS)
    return code, _hash(code)


def check_numeric_code(code_hash: str | None, code: str) -> bool:
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    return bool(code_hash) and len(code) == _DIGITS and hmac.compare_digest(code_hash, _hash(code))
