from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_member_stat_snapshot import NationMemberStatSnapshot
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.models.user import User
from apps.api.app.schemas.nation_stats import (
    NationDonorItemRead,
    NationDonorListResponse,
    NationMemberStatsSyncRequest,
    NationMemberStatsSyncResponse,
    NationRankingItemRead,
    NationRankingResponse,
    NationStatsRead,
    NationStatsUpsertRequest,
    NationStatsUpsertResponse,
    NationTreasuryActionResponse,
    NationTreasuryTransactionListResponse,
    NationTreasuryTransactionRead,
    PlayerStatCacheSyncRequest,
    PlayerStatCacheSyncResponse,
)
from apps.api.app.services.nation_activity_service import NationActivityService
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.services.nation_service import NationNotFoundError

MONEY_QUANT = Decimal("0.01")
MAX_TREASURY_ACTION_AMOUNT = Decimal("9999999999999999.99")


class NationStatsPermissionError(Exception):
    pass


class NationStatsValidationError(Exception):
    pass


class NationStatsService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id
        self.activity = NationActivityService(session, server_id)
        self.cache = RedisCacheService()

    def get_stats_by_slug(self, slug: str) -> NationStatsRead:
        nation = self.session.execute(
            select(Nation).where(Nation.slug == slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        stat = self._get_or_create_for_nation(nation)
        self.session.commit()
        self.session.refresh(stat)

        return NationStatsRead(
            nation_id=stat.nation_id,
            treasury_balance=float(self._as_money(stat.treasury_balance)),
            territory_points=int(stat.territory_points or 0),
            total_playtime_minutes=int(stat.total_playtime_minutes or 0),
            pvp_kills=int(stat.pvp_kills or 0),
            mob_kills=int(stat.mob_kills or 0),
            boss_kills=int(stat.boss_kills or 0),
            deaths=int(stat.deaths or 0),
            blocks_placed=int(stat.blocks_placed or 0),
            blocks_broken=int(stat.blocks_broken or 0),
            events_completed=int(stat.events_completed or 0),
            prestige_score=int(stat.prestige_score or 0),
            updated_at=stat.updated_at,
        )

    def upsert_from_game(self, payload: NationStatsUpsertRequest) -> NationStatsUpsertResponse:
        nation = self.session.execute(
            select(Nation).where(Nation.slug == payload.nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        stat = self._get_or_create_for_nation(nation)

        # ВАЖНО:
        # treasury_balance НЕ трогаем обычным game-stats sync.
        stat.territory_points = int(payload.territory_points or 0)
        stat.total_playtime_minutes = int(payload.total_playtime_minutes or 0)
        stat.pvp_kills = int(payload.pvp_kills or 0)
        stat.mob_kills = int(payload.mob_kills or 0)
        stat.boss_kills = int(payload.boss_kills or 0)
        stat.deaths = int(payload.deaths or 0)
        stat.blocks_placed = int(payload.blocks_placed or 0)
        stat.blocks_broken = int(payload.blocks_broken or 0)
        stat.events_completed = int(payload.events_completed or 0)
        stat.prestige_score = int(payload.prestige_score or 0)

        self.session.commit()
        self.session.refresh(stat)

        for item in payload.members:
            normalized = item.minecraft_nickname.strip().lower()
            self.cache.delete(f"player_skin:{normalized}")
        for snapshot in existing_by_norm.values():
            if snapshot.user_id is not None:
                self.cache.delete(f"launcher_dashboard:user:{snapshot.user_id}")

        return NationStatsUpsertResponse(
            message="Статистика государства обновлена.",
            nation_id=nation.id,
            nation_slug=nation.slug,
            updated_at=stat.updated_at,
        )

    def upsert_member_snapshots_from_game(
        self,
        payload: NationMemberStatsSyncRequest,
    ) -> NationMemberStatsSyncResponse:
        nation = self.session.execute(
            select(Nation).where(Nation.slug == payload.nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        existing = self.session.execute(
            select(NationMemberStatSnapshot).where(
                NationMemberStatSnapshot.nation_id == nation.id
            )
        ).scalars().all()
        existing_by_norm = {
            item.minecraft_nickname_normalized: item for item in existing
        }

        incoming_norms: set[str] = set()

        for item in payload.members:
            normalized = item.minecraft_nickname.strip().lower()
            incoming_norms.add(normalized)

            snapshot = existing_by_norm.get(normalized)
            if snapshot is None:
                snapshot = NationMemberStatSnapshot(
                    server_id=self.server_id,
                    nation_id=nation.id,
                    minecraft_nickname=item.minecraft_nickname.strip(),
                    minecraft_nickname_normalized=normalized,
                )
                self.session.add(snapshot)

            account = self.session.execute(
                select(PlayerAccount).where(
                    PlayerAccount.minecraft_nickname_normalized == normalized
                )
            ).scalar_one_or_none()

            snapshot.user_id = account.user_id if account is not None else None
            snapshot.minecraft_nickname = item.minecraft_nickname.strip()
            snapshot.total_playtime_minutes = max(0, int(item.total_playtime_minutes))
            snapshot.pvp_kills = max(0, int(item.pvp_kills))
            snapshot.mob_kills = max(0, int(item.mob_kills))
            snapshot.deaths = max(0, int(item.deaths))
            snapshot.blocks_placed = max(0, int(item.blocks_placed))
            snapshot.blocks_broken = max(0, int(item.blocks_broken))
            snapshot.current_balance = self._as_money(item.current_balance)
            snapshot.completed_quests = max(0, int(item.completed_quests))
            snapshot.source = (item.source or "cached")[:32]
            snapshot.last_seen_at = item.last_seen_at
            snapshot.last_synced_at = datetime.now(timezone.utc)

        for item in existing:
            if item.minecraft_nickname_normalized not in incoming_norms:
                self.session.delete(item)

        stat = self._recalculate_nation_stats_from_snapshots(
            nation=nation,
            territory_points=payload.territory_points,
            boss_kills=payload.boss_kills,
            events_completed=payload.events_completed,
            prestige_bonus=payload.prestige_bonus,
        )

        self.session.commit()
        self.session.refresh(stat)

        return NationMemberStatsSyncResponse(
            message="Снимки статистики участников государства синхронизированы.",
            nation_id=nation.id,
            nation_slug=nation.slug,
            member_snapshots_synced=len(payload.members),
            updated_at=stat.updated_at,
        )

    def upsert_player_stats_cache(self, payload: PlayerStatCacheSyncRequest) -> PlayerStatCacheSyncResponse:
        for item in payload.players:
            normalized = item.minecraft_nickname.strip().lower()

            cache_entry = self.session.execute(
                select(PlayerStatCache).where(
                    PlayerStatCache.minecraft_nickname_normalized == normalized
                )
            ).scalar_one_or_none()

            if cache_entry is None:
                cache_entry = PlayerStatCache(
                    minecraft_nickname=item.minecraft_nickname.strip(),
                    minecraft_nickname_normalized=normalized,
                )
                self.session.add(cache_entry)

            account = self.session.execute(
                select(PlayerAccount).where(
                    PlayerAccount.minecraft_nickname_normalized == normalized
                )
            ).scalar_one_or_none()

            cache_entry.user_id = account.user_id if account is not None else None
            cache_entry.minecraft_nickname = item.minecraft_nickname.strip()
            cache_entry.total_playtime_minutes = max(0, int(item.total_playtime_minutes))
            cache_entry.pvp_kills = max(0, int(item.pvp_kills))
            cache_entry.mob_kills = max(0, int(item.mob_kills))
            cache_entry.deaths = max(0, int(item.deaths))
            cache_entry.blocks_placed = max(0, int(item.blocks_placed))
            cache_entry.blocks_broken = max(0, int(item.blocks_broken))
            cache_entry.current_balance = self._as_money(item.current_balance)
            cache_entry.completed_quests = max(0, int(item.completed_quests))
            cache_entry.source = (item.source or "live")[:32]
            cache_entry.last_seen_at = item.last_seen_at
            cache_entry.last_synced_at = datetime.now(timezone.utc)

        self.session.commit()
        return PlayerStatCacheSyncResponse(synced=len(payload.players))

    def get_rankings(self) -> NationRankingResponse:
        nations = self.session.execute(
            select(Nation)
            .join(User, User.id == Nation.leader_user_id)
            .where(Nation.is_public.is_(True))
            .where(User.is_admin.is_(False))
            .order_by(Nation.created_at.desc())
        ).scalars().all()

        items: list[NationRankingItemRead] = []
        for nation in nations:
            stat = self.session.execute(
                select(NationStat).where(NationStat.nation_id == nation.id)
            ).scalar_one_or_none()
            members_count = int(
                self.session.query(NationMember)
                .filter(NationMember.nation_id == nation.id)
                .count()
            )

            treasury = float(self._as_money(stat.treasury_balance)) if stat else 0.0
            territory = int(stat.territory_points or 0) if stat else 0
            playtime = int(stat.total_playtime_minutes or 0) if stat else 0
            pvp = int(stat.pvp_kills or 0) if stat else 0
            mob = int(stat.mob_kills or 0) if stat else 0
            prestige = int(stat.prestige_score or 0) if stat else 0

            score = (
                treasury * 0.002
                + territory * 15
                + playtime * 0.05
                + pvp * 8
                + mob * 0.2
                + prestige
                + members_count * 10
            )

            items.append(
                NationRankingItemRead(
                    nation_id=nation.id,
                    slug=nation.slug,
                    title=nation.title,
                    tag=nation.tag,
                    accent_color=nation.accent_color,
                    banner_url=nation.banner_url or nation.banner_preview_url,
                    icon_url=nation.icon_url or nation.icon_preview_url,
                    members_count=members_count,
                    treasury_balance=treasury,
                    territory_points=territory,
                    total_playtime_minutes=playtime,
                    pvp_kills=pvp,
                    mob_kills=mob,
                    prestige_score=prestige,
                    score=round(score, 2),
                )
            )

        items.sort(key=lambda x: x.score, reverse=True)
        return NationRankingResponse(items=items)

    def deposit(
        self,
        *,
        current_user: User,
        nation_slug: str,
        amount: Decimal,
        comment: str | None = None,
    ) -> NationTreasuryActionResponse:
        amount = self._normalize_money_amount(amount)
        nation, stat = self._require_manageable_nation_with_stats(
            current_user,
            nation_slug,
            lock_for_update=True,
        )

        player_account = current_user.player_account
        if player_account is None:
            raise NationStatsValidationError("Игровой профиль не привязан к аккаунту.")

        normalized_nickname = (
            (player_account.minecraft_nickname_normalized or "")
            .strip()
            .lower()
        )
        if not normalized_nickname:
            raise NationStatsValidationError("Игровой профиль не привязан к аккаунту.")

        new_treasury_balance = self._apply_player_balance_deposit(
            nation=nation,
            stat=stat,
            amount=amount,
            actor_user_id=current_user.id,
            minecraft_nickname=player_account.minecraft_nickname,
            normalized_nickname=normalized_nickname,
            comment=comment,
            transaction_type="deposit",
            activity_event_type="nation_treasury_deposit",
            activity_message="Игрок пополнил казну государства.",
            extra_metadata={"source": "web_deposit"},
        )

        self.session.commit()
        self.session.refresh(stat)

        return NationTreasuryActionResponse(
            message="Казна государства пополнена.",
            nation_slug=nation.slug,
            new_treasury_balance=new_treasury_balance,
        )

    def withdraw(
        self,
        *,
        current_user: User,
        nation_slug: str,
        amount: Decimal,
        comment: str | None = None,
    ) -> NationTreasuryActionResponse:
        amount = self._normalize_money_amount(amount)
        nation, stat = self._require_manageable_nation_with_stats(
            current_user,
            nation_slug,
            lock_for_update=True,
        )

        current_balance = self._as_money(stat.treasury_balance)
        if current_balance < amount:
            raise NationStatsValidationError("Недостаточно средств в казне государства.")

        stat.treasury_balance = self._as_money(current_balance - amount)

        self.session.add(
            NationTreasuryTransaction(
                server_id=self.server_id,
                transaction_type="withdraw",
                nation_id=nation.id,
                created_by_user_id=current_user.id,
                gross_amount=amount,
                fee_amount=Decimal("0.00"),
                net_amount=amount,
                comment=comment,
                metadata_json={"nation_slug": nation.slug},
            )
        )

        self.activity.record(
            nation_id=nation.id,
            event_type="nation_treasury_withdraw",
            actor_user_id=current_user.id,
            message="Из казны государства выполнено списание.",
            metadata={
                "amount": str(amount),
                "nation_slug": nation.slug,
                "comment": comment,
            },
        )

        self.session.commit()
        self.session.refresh(stat)

        return NationTreasuryActionResponse(
            message="Средства списаны из казны государства.",
            nation_slug=nation.slug,
            new_treasury_balance=self._as_money(stat.treasury_balance),
        )

    def donate_from_game_player(
        self,
        *,
        nation_slug: str,
        amount: Decimal,
        minecraft_nickname: str,
        comment: str | None = None,
    ) -> NationTreasuryActionResponse:
        amount = self._normalize_money_amount(amount)
        nation = self.session.execute(
            select(Nation).where(Nation.slug == nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        normalized_nickname = minecraft_nickname.strip().lower()
        if not normalized_nickname:
            raise NationStatsValidationError("Некорректный ник игрока.")

        player_account = self.session.execute(
            select(PlayerAccount).where(
                PlayerAccount.minecraft_nickname_normalized == normalized_nickname
            )
        ).scalar_one_or_none()
        if player_account is None:
            raise NationStatsValidationError("Игровой профиль игрока не найден.")

        membership = self.session.execute(
            select(NationMember).where(
                NationMember.nation_id == nation.id,
                NationMember.user_id == player_account.user_id,
            )
        ).scalar_one_or_none()
        if membership is None:
            raise NationStatsValidationError("Игрок не состоит в этом государстве.")

        stat = self._get_or_create_for_nation(nation, lock_for_update=True)

        new_treasury_balance = self._apply_player_balance_deposit(
            nation=nation,
            stat=stat,
            amount=amount,
            actor_user_id=player_account.user_id,
            minecraft_nickname=player_account.minecraft_nickname,
            normalized_nickname=normalized_nickname,
            comment=comment,
            transaction_type="player_donation",
            activity_event_type="nation_treasury_donated_by_player",
            activity_message="Игрок пополнил казну государства.",
            extra_metadata={"source": "game_player_donation"},
        )

        self.session.commit()
        self.session.refresh(stat)

        return NationTreasuryActionResponse(
            message="Игрок пополнил казну государства.",
            nation_slug=nation.slug,
            new_treasury_balance=new_treasury_balance,
        )

    def withdraw_from_game_player(
        self,
        *,
        nation_slug: str,
        amount: Decimal,
        minecraft_nickname: str,
        comment: str | None = None,
    ) -> NationTreasuryActionResponse:
        amount = self._normalize_money_amount(amount)
        nation = self.session.execute(
            select(Nation).where(Nation.slug == nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        normalized_nickname = minecraft_nickname.strip().lower()
        if not normalized_nickname:
            raise NationStatsValidationError("Некорректный ник игрока.")

        player_account = self.session.execute(
            select(PlayerAccount).where(
                PlayerAccount.minecraft_nickname_normalized == normalized_nickname
            )
        ).scalar_one_or_none()
        if player_account is None:
            raise NationStatsValidationError("Игровой профиль игрока не найден.")

        stat = self._get_or_create_for_nation(nation, lock_for_update=True)
        current_balance = self._as_money(stat.treasury_balance)
        if current_balance < amount:
            raise NationStatsValidationError("Недостаточно средств в казне государства.")

        stat.treasury_balance = self._as_money(current_balance - amount)

        self.session.add(
            NationTreasuryTransaction(
                server_id=self.server_id,
                transaction_type="withdraw",
                nation_id=nation.id,
                created_by_user_id=player_account.user_id,
                gross_amount=amount,
                fee_amount=Decimal("0.00"),
                net_amount=amount,
                comment=comment,
                metadata_json={
                    "nation_slug": nation.slug,
                    "minecraft_nickname": minecraft_nickname,
                    "source": "game_player_withdraw",
                },
            )
        )

        self.activity.record(
            nation_id=nation.id,
            event_type="nation_treasury_withdraw",
            actor_user_id=player_account.user_id,
            message="Из казны государства выполнено списание.",
            metadata={
                "amount": str(amount),
                "nation_slug": nation.slug,
                "minecraft_nickname": minecraft_nickname,
                "comment": comment,
            },
        )

        self.session.commit()
        self.session.refresh(stat)

        return NationTreasuryActionResponse(
            message="Средства списаны из казны государства.",
            nation_slug=nation.slug,
            new_treasury_balance=self._as_money(stat.treasury_balance),
        )

    def list_transactions_for_nation(
        self,
        nation_slug: str,
        limit: int = 25,
    ) -> NationTreasuryTransactionListResponse:
        nation = self.session.execute(
            select(Nation).where(Nation.slug == nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        items = self.session.execute(
            select(NationTreasuryTransaction)
            .where(NationTreasuryTransaction.nation_id == nation.id)
            .order_by(NationTreasuryTransaction.created_at.desc())
            .limit(limit)
        ).scalars().all()

        return NationTreasuryTransactionListResponse(
            total=len(items),
            items=[self._serialize_transaction(item) for item in items],
        )

    def list_top_donors_for_nation(
        self,
        nation_slug: str,
        limit: int = 10,
    ) -> NationDonorListResponse:
        nation = self.session.execute(
            select(Nation).where(Nation.slug == nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        rows = self.session.execute(
            select(NationTreasuryTransaction)
            .where(
                NationTreasuryTransaction.nation_id == nation.id,
                NationTreasuryTransaction.transaction_type == "player_donation",
            )
            .order_by(NationTreasuryTransaction.created_at.desc())
        ).scalars().all()

        aggregated: dict[str, dict] = defaultdict(
            lambda: {
                "minecraft_nickname": "unknown",
                "total_amount": Decimal("0.00"),
                "donations_count": 0,
                "last_donated_at": None,
            }
        )

        for row in rows:
            nickname = str(
                (row.metadata_json or {}).get("minecraft_nickname") or "unknown"
            )
            data = aggregated[nickname]
            data["minecraft_nickname"] = nickname
            data["total_amount"] += self._as_money(row.net_amount)
            data["donations_count"] += 1
            if data["last_donated_at"] is None:
                data["last_donated_at"] = row.created_at

        items = sorted(
            [NationDonorItemRead(**item) for item in aggregated.values()],
            key=lambda x: (x.total_amount, x.donations_count),
            reverse=True,
        )[:limit]

        return NationDonorListResponse(total=len(items), items=items)

    def _apply_player_balance_deposit(
        self,
        *,
        nation: Nation,
        stat: NationStat,
        amount: Decimal,
        actor_user_id: UUID | None,
        minecraft_nickname: str,
        normalized_nickname: str,
        comment: str | None,
        transaction_type: str,
        activity_event_type: str,
        activity_message: str,
        extra_metadata: dict[str, object] | None = None,
    ) -> Decimal:
        snapshot = self._get_member_snapshot_for_update(
            nation.id,
            normalized_nickname,
        )
        if snapshot is None:
            raise NationStatsValidationError(
                "Снимок баланса игрока не найден. Сначала обнови данные из игры."
            )

        if actor_user_id is not None:
            if snapshot.user_id is None:
                snapshot.user_id = actor_user_id
            elif snapshot.user_id != actor_user_id:
                raise NationStatsValidationError(
                    "Снимок баланса не соответствует аккаунту игрока."
                )

        player_balance_before = self._as_money(snapshot.current_balance)
        if player_balance_before < amount:
            raise NationStatsValidationError("Недостаточно денег у игрока.")

        player_balance_after = self._as_money(player_balance_before - amount)
        treasury_before = self._as_money(stat.treasury_balance)
        treasury_after = self._as_money(treasury_before + amount)

        snapshot.current_balance = player_balance_after
        stat.treasury_balance = treasury_after

        metadata_json: dict[str, object] = {
            "nation_slug": nation.slug,
            "minecraft_nickname": minecraft_nickname,
            "player_balance_before": str(player_balance_before),
            "player_balance_after": str(player_balance_after),
        }
        if extra_metadata:
            metadata_json.update(extra_metadata)

        self.session.add(
            NationTreasuryTransaction(
                server_id=self.server_id,
                transaction_type=transaction_type,
                nation_id=nation.id,
                created_by_user_id=actor_user_id,
                gross_amount=amount,
                fee_amount=Decimal("0.00"),
                net_amount=amount,
                comment=comment,
                metadata_json=metadata_json,
            )
        )

        self.activity.record(
            nation_id=nation.id,
            event_type=activity_event_type,
            actor_user_id=actor_user_id,
            message=activity_message,
            metadata={
                "nation_slug": nation.slug,
                "amount": str(amount),
                "minecraft_nickname": minecraft_nickname,
                "comment": comment,
                "player_balance_before": str(player_balance_before),
                "player_balance_after": str(player_balance_after),
            },
        )

        return treasury_after

    def _recalculate_nation_stats_from_snapshots(
        self,
        *,
        nation: Nation,
        territory_points: int,
        boss_kills: int,
        events_completed: int,
        prestige_bonus: int,
    ) -> NationStat:
        stat = self._get_or_create_for_nation(nation)

        snapshots = self.session.execute(
            select(NationMemberStatSnapshot).where(
                NationMemberStatSnapshot.nation_id == nation.id
            )
        ).scalars().all()

        total_playtime_minutes = sum(int(item.total_playtime_minutes or 0) for item in snapshots)
        pvp_kills = sum(int(item.pvp_kills or 0) for item in snapshots)
        mob_kills = sum(int(item.mob_kills or 0) for item in snapshots)
        deaths = sum(int(item.deaths or 0) for item in snapshots)
        blocks_placed = sum(int(item.blocks_placed or 0) for item in snapshots)
        blocks_broken = sum(int(item.blocks_broken or 0) for item in snapshots)

        stat.territory_points = int(territory_points or 0)
        stat.total_playtime_minutes = total_playtime_minutes
        stat.pvp_kills = pvp_kills
        stat.mob_kills = mob_kills
        stat.boss_kills = int(boss_kills or 0)
        stat.deaths = deaths
        stat.blocks_placed = blocks_placed
        stat.blocks_broken = blocks_broken
        stat.events_completed = int(events_completed or 0)

        stat.prestige_score = int(
            round(
                stat.territory_points * 15
                + stat.total_playtime_minutes * 0.05
                + stat.pvp_kills * 8
                + stat.mob_kills * 0.2
                + stat.boss_kills * 25
                + stat.events_completed * 20
                + int(prestige_bonus or 0)
            )
        )

        return stat

    def _serialize_transaction(
        self,
        item: NationTreasuryTransaction,
    ) -> NationTreasuryTransactionRead:
        return NationTreasuryTransactionRead(
            id=item.id,
            transaction_type=item.transaction_type,
            nation_id=item.nation_id,
            counterparty_nation_id=item.counterparty_nation_id,
            alliance_id=item.alliance_id,
            created_by_user_id=item.created_by_user_id,
            gross_amount=self._as_money(item.gross_amount),
            fee_amount=self._as_money(item.fee_amount),
            net_amount=self._as_money(item.net_amount),
            comment=item.comment,
            metadata_json=item.metadata_json or {},
            created_at=item.created_at,
        )

    def _require_manageable_nation_with_stats(
        self,
        current_user: User,
        nation_slug: str,
        *,
        lock_for_update: bool = False,
    ) -> tuple[Nation, NationStat]:
        nation = self.session.execute(
            select(Nation).where(Nation.slug == nation_slug, Nation.server_id == self.server_id)
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("Государство не найдено.")

        membership = self.session.execute(
            select(NationMember).where(
                NationMember.nation_id == nation.id,
                NationMember.user_id == current_user.id,
            )
        ).scalar_one_or_none()

        if membership is None or membership.role not in {"leader", "officer"}:
            raise NationStatsPermissionError(
                "Недостаточно прав для управления казной государства."
            )

        stat = self._get_or_create_for_nation(nation, lock_for_update=lock_for_update)
        return nation, stat

    def _get_member_snapshot_for_update(
        self,
        nation_id: UUID,
        normalized_nickname: str,
    ) -> NationMemberStatSnapshot | None:
        return self.session.execute(
            select(NationMemberStatSnapshot)
            .where(
                NationMemberStatSnapshot.nation_id == nation_id,
                NationMemberStatSnapshot.minecraft_nickname_normalized == normalized_nickname,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def _get_or_create_for_nation(
        self,
        nation: Nation,
        *,
        lock_for_update: bool = False,
    ) -> NationStat:
        statement = select(NationStat).where(NationStat.nation_id == nation.id)
        if lock_for_update:
            statement = statement.with_for_update()

        stat = self.session.execute(statement).scalar_one_or_none()
        if stat is None:
            stat = NationStat(server_id=self.server_id, nation_id=nation.id)
            self.session.add(stat)
            self.session.flush()
        return stat

    def _normalize_money_amount(self, value: Decimal) -> Decimal:
        try:
            amount = Decimal(str(value))
        except Exception as exc:
            raise NationStatsValidationError("Некорректная сумма операции.") from exc

        if not amount.is_finite():
            raise NationStatsValidationError("Некорректная сумма операции.")

        if amount <= 0:
            raise NationStatsValidationError("Сумма должна быть больше нуля.")

        quantized = amount.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        if quantized != amount:
            raise NationStatsValidationError(
                "Сумма может содержать не больше двух знаков после запятой."
            )

        if quantized > MAX_TREASURY_ACTION_AMOUNT:
            raise NationStatsValidationError("Сумма слишком большая.")

        return quantized

    def apply_treasury_tax(self, rate: float) -> dict:
        """Apply a flat-rate tax to all nation treasuries. Called weekly by WealthTax plugin."""
        if not (0 < rate <= 1):
            raise NationStatsValidationError("Ставка налога должна быть от 0 до 1.")

        stats = self.session.execute(
            select(NationStat).where(NationStat.treasury_balance > 0)
        ).scalars().all()

        taxed_count = 0
        total_collected = Decimal("0.00")

        for stat in stats:
            balance = self._as_money(stat.treasury_balance)
            tax = (balance * Decimal(str(rate))).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            if tax < Decimal("0.01"):
                continue

            stat.treasury_balance = self._as_money(balance - tax)
            self.session.add(
                NationTreasuryTransaction(
                    server_id=self.server_id,
                    transaction_type="tax",
                    nation_id=stat.nation_id,
                    created_by_user_id=None,
                    gross_amount=tax,
                    fee_amount=Decimal("0.00"),
                    net_amount=tax,
                    comment=f"Прогрессивный налог на казну ({rate * 100:.1f}%)",
                    metadata_json={"rate": rate, "balance_before": str(balance)},
                )
            )
            taxed_count += 1
            total_collected += tax

        self.session.commit()
        return {"taxed_nations": taxed_count, "total_collected": float(total_collected)}

    def _as_money(self, value: Decimal | float | int | str | None) -> Decimal:
        raw = Decimal(str(value or 0))
        return raw.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

