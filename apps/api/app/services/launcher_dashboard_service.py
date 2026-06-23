from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.nation_activity_log import NationActivityLog
from apps.api.app.models.nation_member_stat_snapshot import NationMemberStatSnapshot
from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.models.user import User
from apps.api.app.schemas.launcher_dashboard import (
    LauncherDashboardActivityItemRead,
    LauncherDashboardNationRead,
    LauncherDashboardPlayerStatsRead,
    LauncherDashboardRead,
)
from apps.api.app.services.nation_service import NationService
from apps.api.app.services.nation_stats_service import NationStatsService
from apps.api.app.services.redis_cache_service import RedisCacheService


class LauncherDashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.nation_service = NationService(session)
        self.nation_stats_service = NationStatsService(session)
        self.cache = RedisCacheService()

    def get_for_user(self, current_user: User) -> LauncherDashboardRead:
        cache_key = f"launcher_dashboard:user:{current_user.id}"
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            return LauncherDashboardRead.model_validate(cached)

        nation_read = self.nation_service.get_my_nation(current_user)
        if nation_read is None:
            player_stats = self._player_stats_from_cache(current_user)
            wallet_balance = player_stats.current_balance if player_stats is not None else 0.0
            payload = LauncherDashboardRead(
                player_stats=player_stats,
                wallet_balance=wallet_balance,
            )
            self.cache.set_json(cache_key, payload.model_dump(mode="json"), ttl_seconds=15)
            return payload

        nation_stats = self.nation_stats_service.get_stats_by_slug(nation_read.slug)

        snapshot = self.session.execute(
            select(NationMemberStatSnapshot).where(
                NationMemberStatSnapshot.nation_id == nation_read.id,
                NationMemberStatSnapshot.user_id == current_user.id,
            )
        ).scalar_one_or_none()

        if snapshot is None and current_user.player_account is not None:
            normalized = current_user.player_account.minecraft_nickname_normalized
            snapshot = self.session.execute(
                select(NationMemberStatSnapshot).where(
                    NationMemberStatSnapshot.nation_id == nation_read.id,
                    NationMemberStatSnapshot.minecraft_nickname_normalized == normalized,
                )
            ).scalar_one_or_none()

        activity_rows = self.session.execute(
            select(NationActivityLog)
            .where(NationActivityLog.nation_id == nation_read.id)
            .order_by(NationActivityLog.created_at.desc())
            .limit(6)
        ).scalars().all()

        dashboard_nation = LauncherDashboardNationRead(
            id=nation_read.id,
            slug=nation_read.slug,
            title=nation_read.title,
            tag=nation_read.tag,
            accent_color=nation_read.accent_color,
            role=nation_read.viewer_role,
            icon_url=nation_read.assets.icon_url,
            icon_preview_url=nation_read.assets.icon_preview_url,
            banner_url=nation_read.assets.banner_url,
            banner_preview_url=nation_read.assets.banner_preview_url,
            background_url=nation_read.assets.background_url,
            background_preview_url=nation_read.assets.background_preview_url,
            alliance_title=nation_read.alliance_summary.title if nation_read.alliance_summary else None,
            alliance_tag=nation_read.alliance_summary.tag if nation_read.alliance_summary else None,
        )

        player_stats = None
        wallet_balance = 0.0

        if snapshot is not None:
            wallet_balance = float(snapshot.current_balance or 0)
            player_stats = LauncherDashboardPlayerStatsRead(
                user_id=snapshot.user_id,
                minecraft_nickname=snapshot.minecraft_nickname,
                total_playtime_minutes=int(snapshot.total_playtime_minutes or 0),
                pvp_kills=int(snapshot.pvp_kills or 0),
                mob_kills=int(snapshot.mob_kills or 0),
                deaths=int(snapshot.deaths or 0),
                blocks_placed=int(snapshot.blocks_placed or 0),
                blocks_broken=int(snapshot.blocks_broken or 0),
                current_balance=wallet_balance,
                completed_quests=int(snapshot.completed_quests or 0),
                source=snapshot.source or "missing",
                last_seen_at=snapshot.last_seen_at,
                last_synced_at=snapshot.last_synced_at,
            )

        payload = LauncherDashboardRead(
            nation=dashboard_nation,
            nation_stats=nation_stats,
            player_stats=player_stats,
            recent_activity=[
                LauncherDashboardActivityItemRead(
                    id=item.id,
                    event_type=item.event_type,
                    message=item.message,
                    created_at=item.created_at,
                )
                for item in activity_rows
            ],
            wallet_balance=wallet_balance,
        )
        self.cache.set_json(cache_key, payload.model_dump(mode="json"), ttl_seconds=15)
        return payload

    def _player_stats_from_cache(self, current_user: User) -> LauncherDashboardPlayerStatsRead | None:
        entry = self.session.execute(
            select(PlayerStatCache).where(PlayerStatCache.user_id == current_user.id)
        ).scalar_one_or_none()

        if entry is None and current_user.player_account is not None:
            normalized = current_user.player_account.minecraft_nickname_normalized
            entry = self.session.execute(
                select(PlayerStatCache).where(
                    PlayerStatCache.minecraft_nickname_normalized == normalized
                )
            ).scalar_one_or_none()

        if entry is None:
            return None

        return LauncherDashboardPlayerStatsRead(
            user_id=entry.user_id,
            minecraft_nickname=entry.minecraft_nickname,
            total_playtime_minutes=int(entry.total_playtime_minutes or 0),
            pvp_kills=int(entry.pvp_kills or 0),
            mob_kills=int(entry.mob_kills or 0),
            deaths=int(entry.deaths or 0),
            blocks_placed=int(entry.blocks_placed or 0),
            blocks_broken=int(entry.blocks_broken or 0),
            current_balance=float(entry.current_balance or 0),
            completed_quests=int(entry.completed_quests or 0),
            source=entry.source or "cached",
            last_seen_at=entry.last_seen_at,
            last_synced_at=entry.last_synced_at,
        )
