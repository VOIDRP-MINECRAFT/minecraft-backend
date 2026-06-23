from __future__ import annotations

import re

SITE_LOGIN_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
MINECRAFT_NICKNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,16}$")


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_site_login(value: str) -> tuple[str, str]:
    raw = value.strip()
    normalized = raw.lower()
    if not SITE_LOGIN_PATTERN.fullmatch(raw):
        raise ValueError(
            "site_login must contain only letters, numbers, underscore, dot or hyphen"
        )
    return raw, normalized


def normalize_minecraft_nickname(value: str) -> tuple[str, str]:
    raw = value.strip()
    normalized = raw.lower()
    if not MINECRAFT_NICKNAME_PATTERN.fullmatch(raw):
        raise ValueError(
            "minecraft_nickname must contain only letters, numbers and underscore"
        )
    return raw, normalized
