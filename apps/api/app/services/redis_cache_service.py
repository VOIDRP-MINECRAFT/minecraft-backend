from __future__ import annotations

import json
from fnmatch import fnmatch

from apps.api.app.config import get_settings

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


class RedisCacheService:
    def __init__(self) -> None:
        settings = get_settings()
        self.prefix = (settings.redis_prefix or "voidrp").strip() or "voidrp"
        self.default_ttl = max(1, int(settings.redis_default_ttl_seconds or 30))
        self._client = None
        if redis is not None:
            try:
                self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            except Exception:
                self._client = None

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def get_json(self, key: str):
        if self._client is None:
            return None
        try:
            raw = self._client.get(self._key(key))
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def set_json(self, key: str, value, ttl_seconds: int | None = None) -> None:
        if self._client is None:
            return
        try:
            ttl = max(1, int(ttl_seconds or self.default_ttl))
            self._client.setex(self._key(key), ttl, json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return

    def delete(self, key: str) -> None:
        if self._client is None:
            return
        try:
            self._client.delete(self._key(key))
        except Exception:
            return

    def delete_pattern(self, pattern: str) -> None:
        if self._client is None:
            return
        try:
            full_pattern = self._key(pattern)
            for key in self._client.scan_iter(match=full_pattern):
                self._client.delete(key)
        except Exception:
            return
