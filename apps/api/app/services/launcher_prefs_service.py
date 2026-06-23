from __future__ import annotations

import json

from sqlalchemy.orm import Session

from apps.api.app.models.launcher_preferences import LauncherPreferences
from apps.api.app.models.user import User
from apps.api.app.schemas.launcher_prefs import (
    LauncherConfigFileRead,
    LauncherConfigFileUpdate,
    LauncherModPrefsUpdate,
    LauncherPreferencesRead,
)

# Only these config paths can be stored per-account (prevent abuse)
ALLOWED_CONFIG_PATHS: frozenset[str] = frozenset(
    {
        "options.txt",
        "config/sodium-options.json",
        "config/sodium-extra-options.json",
        "config/sodium-extra.json",
    }
)
MAX_CONTENT_B64_LEN = 512 * 1024  # 512 KB in base64 chars


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
        if path not in ALLOWED_CONFIG_PATHS:
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
        if data.path not in ALLOWED_CONFIG_PATHS:
            raise ValueError(f"Config path '{data.path}' is not allowed")
        if len(data.content_b64) > MAX_CONTENT_B64_LEN:
            raise ValueError("Config file content too large")
        prefs = self._get_or_create(user)
        try:
            config_files: dict[str, str] = json.loads(prefs.config_files_json or "{}")
        except Exception:
            config_files = {}
        config_files[data.path] = data.content_b64
        prefs.config_files_json = json.dumps(config_files)
        self._session.commit()
