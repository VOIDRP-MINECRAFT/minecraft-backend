from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from apps.api.app.models.launcher_preferences import LauncherPreferences
from apps.api.app.models.user import User
from apps.api.app.schemas.launcher_prefs import (
    LauncherConfigFileRead,
    LauncherConfigFileUpdate,
    LauncherModPrefsUpdate,
    LauncherPreferencesRead,
)

# The files a player edits from inside the game — keys, video, sound, and the settings of
# the mods that keep their own file. Anything else is refused: this is a slot on someone's
# account, not a file store.
ALLOWED_CONFIG_PATHS: frozenset[str] = frozenset(
    {
        # Keys, video, sound, chat. Mod keybinds live in here too.
        "options.txt",
        # Graphics, by whichever renderer the pack ships.
        "config/sodium-options.json",
        "config/sodium-extra-options.json",
        "config/sodium-extra.json",
        "config/embeddium-options.json",
        "config/iris.properties",
    }
)
# A slot per server: the same account plays packs of different Minecraft versions, and one
# shared slot means the settings of the last server played are restored onto the next one.
# The key is "<slug>/<path>"; a bare "<path>" is what the launcher wrote before this and is
# still read, so nobody loses what is already saved.
SERVER_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MAX_CONTENT_B64_LEN = 512 * 1024  # 512 KB in base64 chars
# Everything one account may keep, across every server and file. At about 60 KB for an
# options.txt this is room for a dozen servers and then some.
MAX_TOTAL_B64_LEN = 4 * 1024 * 1024


def split_config_path(key: str) -> tuple[str | None, str]:
    """Splits "<slug>/<path>" into its parts; a bare path has no slug."""
    head, _, rest = key.partition("/")
    if rest and SERVER_SLUG_RE.match(head) and rest in ALLOWED_CONFIG_PATHS:
        return head, rest
    return None, key


def is_allowed_config_path(key: str) -> bool:
    slug, path = split_config_path(key)
    return path in ALLOWED_CONFIG_PATHS and (slug is None or bool(SERVER_SLUG_RE.match(slug)))


class LauncherPrefsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_or_create(self, user: User) -> LauncherPreferences:
        prefs = (
            self._session.query(LauncherPreferences)
            .filter_by(user_id=user.id)
            .first()
        )
        if prefs is None:
            prefs = LauncherPreferences(
                user_id=user.id,
                disabled_mods_json="[]",
                config_files_json="{}",
            )
            self._session.add(prefs)
            self._session.flush()
        return prefs

    def get(self, user: User) -> LauncherPreferencesRead:
        prefs = self._get_or_create(user)
        try:
            disabled_mods: list[str] = json.loads(prefs.disabled_mods_json or "[]")
        except Exception:
            disabled_mods = []
        try:
            config_files: dict[str, str] = json.loads(prefs.config_files_json or "{}")
        except Exception:
            config_files = {}
        return LauncherPreferencesRead(disabled_mods=disabled_mods, config_files=config_files)

    def save_mods(self, user: User, data: LauncherModPrefsUpdate) -> LauncherPreferencesRead:
        prefs = self._get_or_create(user)
        cleaned = [p for p in data.disabled_mods if isinstance(p, str) and p]
        prefs.disabled_mods_json = json.dumps(cleaned)
        self._session.commit()
        return self.get(user)

    def get_config_file(self, user: User, path: str) -> LauncherConfigFileRead:
        if not is_allowed_config_path(path):
            return LauncherConfigFileRead(path=path, found=False)
        prefs = self._get_or_create(user)
        try:
            config_files: dict[str, str] = json.loads(prefs.config_files_json or "{}")
        except Exception:
            config_files = {}
        content = config_files.get(path)
        if content is None:
            return LauncherConfigFileRead(path=path, found=False)
        return LauncherConfigFileRead(path=path, found=True, content_b64=content)

    def save_config_file(self, user: User, data: LauncherConfigFileUpdate) -> None:
        if not is_allowed_config_path(data.path):
            raise ValueError(f"Config path '{data.path}' is not allowed")
        if len(data.content_b64) > MAX_CONTENT_B64_LEN:
            raise ValueError("Config file content too large")
        prefs = self._get_or_create(user)
        try:
            config_files: dict[str, str] = json.loads(prefs.config_files_json or "{}")
        except Exception:
            config_files = {}
        config_files[data.path] = data.content_b64
        total = sum(len(value) for value in config_files.values())
        if total > MAX_TOTAL_B64_LEN:
            raise ValueError("Saved settings are too large for one account")
        prefs.config_files_json = json.dumps(config_files)
        self._session.commit()
