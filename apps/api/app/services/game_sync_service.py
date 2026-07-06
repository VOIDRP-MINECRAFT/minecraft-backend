from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.core.security import utc_now
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.referral_reward_period import ReferralRewardPeriod
from apps.api.app.models.user import User
from apps.api.app.schemas.game_sync import (
    GameNationListResponse,
    GameNationMembershipMemberRead,
    GameNationMembershipSyncRequest,
    GameNationMembershipSyncResponse,
    GameNationSummaryResponse,
    GameNationSyncItemRead,
    GameReferralRewardRead,
    GameReferralRewardResolveResponse,
    NationCapitalUpdateRequest,
)
from apps.api.app.services.nation_activity_service import NationActivityService
from apps.api.app.services.nation_service import NationNotFoundError
from apps.api.app.utils.normalization import normalize_minecraft_nickname

CAPITAL_REWARD_AMOUNT = Decimal("50000.00")


class GameSyncValidationError(Exception):
    pass


class GameSyncService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def list_nations_for_game_sync(self) -> GameNationListResponse:
        nations = (
            self.session.execute(
                select(Nation)
                .where(Nation.server_id == self.server_id)
                .options(
                    joinedload(Nation.members)
                    .joinedload(NationMember.user)
                    .joinedload(User.player_account)
                )
                .order_by(Nation.created_at.desc())
            )
            .unique()
            .scalars()
            .all()
        )

        items: list[GameNationSyncItemRead] = []
        for nation in nations:
            leader_nickname = None
            officers: list[str] = []
            members: list[str] = []
            member_custom_prefixes: dict[str, str] = {}

            for membership in nation.members or []:
                user = membership.user
                account = user.player_account if user is not None else None
                nickname = account.minecraft_nickname if account is not None else None
                if not nickname:
                    continue

                if membership.role == "leader":
                    leader_nickname = nickname
                elif membership.role == "officer":
                    officers.append(nickname)
                else:
                    members.append(nickname)

                if membership.custom_prefix:
                    member_custom_prefixes[nickname] = membership.custom_prefix

            if leader_nickname is None:
                leader_user = next((item.user for item in nation.members if item.user_id == nation.leader_user_id), None)
                if leader_user is not None and leader_user.player_account is not None:
                    leader_nickname = leader_user.player_account.minecraft_nickname

            items.append(
                GameNationSyncItemRead(
                    nation_id=nation.id,
                    nation_slug=nation.slug,
                    title=nation.title,
                    tag=nation.tag,
                    accent_color=nation.accent_color,
                    capital_x=nation.capital_x,
                    capital_z=nation.capital_z,
                    capital_world=nation.capital_world,
                    leader_minecraft_nickname=leader_nickname,
                    officers=sorted(set(officers)),
                    members=sorted(set(members)),
                    member_custom_prefixes=member_custom_prefixes,
                    updated_at=nation.updated_at,
                )
            )

        return GameNationListResponse(total=len(items), items=items)

    def get_nation_summary(self, slug: str) -> GameNationSummaryResponse:
        nation = self._get_nation_by_slug(slug)
        if nation is None:
            raise NationNotFoundError("nation was not found")

        members = list(nation.members or [])
        officers_count = len([item for item in members if item.role == "officer"])

        return GameNationSummaryResponse(
            nation_id=nation.id,
            nation_slug=nation.slug,
            title=nation.title,
            tag=nation.tag,
            leader_user_id=nation.leader_user_id,
            members_count=len(members),
            officers_count=officers_count,
            updated_at=nation.updated_at,
        )

    def sync_nation_membership(
        self,
        slug: str,
        payload: GameNationMembershipSyncRequest,
    ) -> GameNationMembershipSyncResponse:
        nation = self._get_nation_by_slug(slug)
        if nation is None:
            raise NationNotFoundError("nation was not found")

        desired_roles = self._build_desired_roles(payload)

        matched_accounts: dict[str, PlayerAccount] = {}
        unresolved_nicknames: list[str] = []

        for nickname, _role in desired_roles.items():
            account = self._get_player_account_by_minecraft_nickname(nickname)
            if account is None or account.user is None:
                unresolved_nicknames.append(nickname)
                continue
            matched_accounts[nickname] = account

        desired_user_roles: dict = {}
        for nickname, role in desired_roles.items():
            account = matched_accounts.get(nickname)
            if account is None:
                continue
            desired_user_roles[account.user_id] = role

        if not desired_user_roles:
            raise GameSyncValidationError("no valid player accounts were resolved for membership sync")

        current_members_by_user_id = {item.user_id: item for item in nation.members}

        removed_user_ids: list = []
        for user_id, role in desired_user_roles.items():
            existing = current_members_by_user_id.get(user_id)
            if existing is None:
                self.session.add(
                    NationMember(
                        server_id=self.server_id,
                        nation_id=nation.id,
                        user_id=user_id,
                        role=role,
                    )
                )
            else:
                existing.role = role

        if payload.replace_missing:
            desired_user_ids = set(desired_user_roles.keys())
            for member in list(nation.members):
                if member.user_id not in desired_user_ids:
                    removed_user_ids.append(member.user_id)
                    self.session.delete(member)

        leader_user_id = None
        leader_nickname = payload.leader_minecraft_nickname.strip() if payload.leader_minecraft_nickname else None
        if leader_nickname:
            leader_account = matched_accounts.get(leader_nickname)
            if leader_account is None:
                raise GameSyncValidationError("leader nickname could not be resolved to a player account")
            leader_user_id = leader_account.user_id
            nation.leader_user_id = leader_user_id

            leader_membership = self.session.execute(
                select(NationMember).where(
                    NationMember.nation_id == nation.id,
                    NationMember.user_id == leader_user_id,
                )
            ).scalar_one_or_none()

            if leader_membership is None:
                self.session.add(
                    NationMember(
                        server_id=self.server_id,
                        nation_id=nation.id,
                        user_id=leader_user_id,
                        role="leader",
                    )
                )
            else:
                leader_membership.role = "leader"

        self.session.commit()

        refreshed_nation = self._get_nation_by_slug(slug)
        if refreshed_nation is None:
            raise NationNotFoundError("nation was not found after sync")

        matched_members = self._build_members_read(refreshed_nation.members)

        return GameNationMembershipSyncResponse(
            message="Nation membership synced successfully.",
            nation_id=refreshed_nation.id,
            nation_slug=refreshed_nation.slug,
            leader_user_id=refreshed_nation.leader_user_id,
            matched_members=matched_members,
            unresolved_nicknames=sorted(set(unresolved_nicknames)),
            removed_user_ids=removed_user_ids,
            updated_at=refreshed_nation.updated_at,
        )

    def resolve_active_referral_reward(
        self,
        minecraft_nickname: str,
    ) -> GameReferralRewardResolveResponse:
        raw_nickname, normalized_nickname = normalize_minecraft_nickname(minecraft_nickname)

        account = self.session.execute(
            select(PlayerAccount)
            .options(joinedload(PlayerAccount.user))
            .where(PlayerAccount.minecraft_nickname_normalized == normalized_nickname)
        ).scalar_one_or_none()

        if account is None or account.user is None:
            return GameReferralRewardResolveResponse(
                minecraft_nickname=raw_nickname,
                player_exists=False,
                has_active_reward=False,
                reward=None,
            )

        reward = self.session.execute(
            select(ReferralRewardPeriod).where(
                ReferralRewardPeriod.server_id == self.server_id,
                ReferralRewardPeriod.user_id == account.user_id,
                ReferralRewardPeriod.reward_state == "active",
                ReferralRewardPeriod.expires_at > utc_now(),
            )
            .order_by(ReferralRewardPeriod.expires_at.desc())
        ).scalar_one_or_none()

        if reward is None:
            return GameReferralRewardResolveResponse(
                minecraft_nickname=account.minecraft_nickname,
                player_exists=True,
                has_active_reward=False,
                reward=None,
            )

        bundle_key, perks = self._reward_bundle_for_rank(reward.referral_rank)

        return GameReferralRewardResolveResponse(
            minecraft_nickname=account.minecraft_nickname,
            player_exists=True,
            has_active_reward=True,
            reward=GameReferralRewardRead(
                referral_rank=reward.referral_rank,
                starts_at=reward.starts_at,
                expires_at=reward.expires_at,
                reward_state=reward.reward_state,
                source_qualified_referrals=reward.source_qualified_referrals,
                reward_bundle_key=bundle_key,
                game_perks=perks,
            ),
        )

    def set_nation_capital(self, slug: str, payload: NationCapitalUpdateRequest) -> None:
        nation = self.session.execute(
            select(Nation).where(
                Nation.slug == slug,
                Nation.server_id == self.server_id,
            )
        ).scalar_one_or_none()
        if nation is None:
            raise NationNotFoundError("nation was not found")

        first_time = nation.capital_world is None

        nation.capital_x = payload.capital_x
        nation.capital_z = payload.capital_z
        nation.capital_world = payload.capital_world

        if first_time:
            self._grant_capital_reward(nation)

        self.session.commit()

    def _grant_capital_reward(self, nation: Nation) -> None:
        stat = self.session.execute(
            select(NationStat).where(NationStat.nation_id == nation.id)
        ).scalar_one_or_none()
        if stat is None:
            stat = NationStat(server_id=self.server_id, nation_id=nation.id)
            self.session.add(stat)
            self.session.flush()

        current = Decimal(str(stat.treasury_balance or 0))
        stat.treasury_balance = current + CAPITAL_REWARD_AMOUNT

        self.session.add(
            NationTreasuryTransaction(
                server_id=self.server_id,
                transaction_type="capital_reward",
                nation_id=nation.id,
                created_by_user_id=None,
                gross_amount=CAPITAL_REWARD_AMOUNT,
                fee_amount=Decimal("0.00"),
                net_amount=CAPITAL_REWARD_AMOUNT,
                comment="Награда за установку столицы государства.",
                metadata_json={"nation_slug": nation.slug},
            )
        )

        NationActivityService(self.session, self.server_id).record(
            nation_id=nation.id,
            event_type="capital_reward_granted",
            actor_user_id=None,
            message="Государство получило 50 000 за установку столицы.",
            metadata={"amount": str(CAPITAL_REWARD_AMOUNT)},
        )

    def _build_desired_roles(self, payload: GameNationMembershipSyncRequest) -> dict[str, str]:
        desired: dict[str, str] = {}

        for nickname in payload.members:
            raw, _normalized = normalize_minecraft_nickname(nickname)
            desired[raw] = "member"

        for nickname in payload.officers:
            raw, _normalized = normalize_minecraft_nickname(nickname)
            desired[raw] = "officer"

        if payload.leader_minecraft_nickname:
            raw, _normalized = normalize_minecraft_nickname(payload.leader_minecraft_nickname)
            desired[raw] = "leader"

        return desired

    def _build_members_read(self, members: Iterable[NationMember]) -> list[GameNationMembershipMemberRead]:
        result: list[GameNationMembershipMemberRead] = []
        ordered = sorted(
            members,
            key=lambda item: (
                0 if item.role == "leader" else 1 if item.role == "officer" else 2,
                item.created_at,
            ),
        )

        for member in ordered:
            user = member.user
            if user is None or user.player_account is None:
                continue

            result.append(
                GameNationMembershipMemberRead(
                    user_id=user.id,
                    site_login=user.site_login,
                    minecraft_nickname=user.player_account.minecraft_nickname,
                    role=member.role,
                )
            )

        return result

    def _get_nation_by_slug(self, slug: str) -> Nation | None:
        return (
            self.session.execute(
                select(Nation)
                .options(
                    joinedload(Nation.members)
                    .joinedload(NationMember.user)
                    .joinedload(User.player_account)
                )
                .where(
                    Nation.slug == slug,
                    Nation.server_id == self.server_id,
                )
            )
            .unique()
            .scalar_one_or_none()
        )

    def _get_player_account_by_minecraft_nickname(self, nickname: str) -> PlayerAccount | None:
        _raw, normalized = normalize_minecraft_nickname(nickname)

        return self.session.execute(
            select(PlayerAccount)
            .options(joinedload(PlayerAccount.user))
            .where(PlayerAccount.minecraft_nickname_normalized == normalized)
        ).scalar_one_or_none()

    def _reward_bundle_for_rank(self, rank: str) -> tuple[str, list[str]]:
        mapping = {
            "rank_3": (
                "referral_rank_3",
                [
                    "referral.rank_3",
                    "kit.referral_3",
                    "bonus.money.small",
                ],
            ),
            "rank_2": (
                "referral_rank_2",
                [
                    "referral.rank_2",
                    "kit.referral_2",
                    "bonus.money.medium",
                    "crate.referral_2",
                ],
            ),
            "rank_1": (
                "referral_rank_1",
                [
                    "referral.rank_1",
                    "kit.referral_1",
                    "bonus.money.large",
                    "crate.referral_1",
                    "prefix.referral_1",
                ],
            ),
        }

        return mapping.get(
            rank,
            (
                "referral_unknown",
                [],
            ),
        )
