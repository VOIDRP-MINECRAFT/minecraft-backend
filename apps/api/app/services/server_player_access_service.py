from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.utils.normalization import normalize_minecraft_nickname


@dataclass(slots=True)
class PlayerAccessResult:
    player_exists: bool
    user_active: bool
    legacy_auth_enabled: bool
    must_use_launcher: bool
    minecraft_nickname: str | None = None
    error: str | None = None


class ServerPlayerAccessService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.cache = RedisCacheService()

    def get_player_access(self, *, player_name: str) -> PlayerAccessResult:
        raw_name, normalized_name = normalize_minecraft_nickname(player_name)
        cache_key = f"player_access:{normalized_name}"

        cached = self.cache.get_json(cache_key)
        if isinstance(cached, dict):
            try:
                return PlayerAccessResult(**cached)
            except TypeError:
                self.cache.delete(cache_key)

        player_account = self.session.execute(
            select(PlayerAccount)
            .options(joinedload(PlayerAccount.user))
            .where(PlayerAccount.minecraft_nickname_normalized == normalized_name)
        ).unique().scalar_one_or_none()

        if player_account is None or player_account.user is None:
            payload = PlayerAccessResult(
                player_exists=False,
                user_active=False,
                legacy_auth_enabled=False,
                must_use_launcher=True,
                minecraft_nickname=raw_name,
                error="player account was not found",
            )
            self.cache.set_json(cache_key, asdict(payload), ttl_seconds=15)
            return payload

        user = player_account.user
        user_active = bool(user.is_active)
        legacy_enabled = bool(player_account.legacy_auth_enabled)

        payload = PlayerAccessResult(
            player_exists=True,
            user_active=user_active,
            legacy_auth_enabled=legacy_enabled,
            must_use_launcher=user_active and not legacy_enabled,
            minecraft_nickname=player_account.minecraft_nickname,
            error=None if user_active else "account is disabled",
        )
        self.cache.set_json(cache_key, asdict(payload), ttl_seconds=15)
        return payload
