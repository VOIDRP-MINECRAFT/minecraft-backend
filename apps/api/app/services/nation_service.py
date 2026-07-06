from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models.alliance import Alliance, AllianceMember
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_join_request import NationJoinRequest
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_member_stat_snapshot import NationMemberStatSnapshot
from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.models.user import User
from apps.api.app.schemas.nation import (
    NationActionResponse,
    NationAllianceMemberSummaryRead,
    NationAllianceSummaryRead,
    NationAssetsRead,
    NationCreateRequest,
    NationDisbandResponse,
    NationJoinActionResponse,
    NationJoinRequestCreate,
    NationJoinRequestRead,
    NationListResponse,
    NationMemberPrefixUpdateRequest,
    NationMemberRead,
    NationMemberRoleUpdateRequest,
    NationRead,
    NationStatsRead,
    NationTransferLeadershipRequest,
    NationUpdateRequest,
)
from apps.api.app.services.nation_activity_service import NationActivityService

SLUG_CLEANUP_PATTERN = re.compile(r"[^a-z0-9._-]+")
MIN_NATION_CREATE_BALANCE = Decimal("300000")


class NationNotFoundError(Exception):
    pass


class NationConflictError(Exception):
    pass


class NationPermissionError(Exception):
    pass


class NationValidationError(Exception):
    pass


class NationService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id
        self.activity_service = NationActivityService(session, server_id)

    def list_public(self, viewer: User | None = None) -> NationListResponse:
        nations = (
            self.session.execute(
                select(Nation)
                .join(User, User.id == Nation.leader_user_id)
                .options(
                    joinedload(Nation.members).joinedload(NationMember.user).joinedload(User.player_account),
                    joinedload(Nation.join_requests).joinedload(NationJoinRequest.user).joinedload(User.player_account),
                )
                .where(Nation.server_id == self.server_id)
                .where(Nation.is_public.is_(True))
                .where(User.is_admin.is_(False))
                .order_by(Nation.created_at.desc())
            )
            .unique()
            .scalars()
            .all()
        )
        return NationListResponse(total=len(nations), items=[self._build_read(item, viewer=viewer) for item in nations])

    def get_my_nation(self, current_user: User) -> NationRead | None:
        nation = self._find_nation_for_user(current_user.id)
        return None if nation is None else self._build_read(nation, viewer=current_user)

    def get_by_slug(self, slug: str, viewer: User | None = None) -> NationRead:
        nation = self._get_nation_by_slug(slug)
        if nation is None:
            raise NationNotFoundError("nation was not found")
        if not nation.is_public and not self._can_manage(nation, viewer):
            raise NationNotFoundError("nation was not found")
        return self._build_read(nation, viewer=viewer)

    def create(self, current_user: User, payload: NationCreateRequest) -> NationRead:
        if self._find_nation_for_user(current_user.id) is not None:
            raise NationConflictError("user is already in a nation")

        self._require_min_balance_for_create(current_user)

        slug = self._normalize_slug(payload.slug)
        if self._slug_exists(slug):
            raise NationConflictError("nation slug is already taken")

        nation = Nation(
            server_id=self.server_id,
            slug=slug,
            title=payload.title.strip(),
            tag=payload.tag.strip().upper(),
            short_description=(payload.short_description or "").strip() or None,
            description=(payload.description or "").strip() or None,
            accent_color=(payload.accent_color or "").strip() or None,
            recruitment_policy=payload.recruitment_policy,
            is_public=payload.is_public,
            leader_user_id=current_user.id,
            created_by_user_id=current_user.id,
        )
        self.session.add(nation)
        self.session.flush()

        self.session.add(
            NationMember(
                server_id=self.server_id,
                nation_id=nation.id,
                user_id=current_user.id,
                role="leader",
            )
        )

        self.activity_service.record(
            nation_id=nation.id,
            event_type="nation_created",
            actor_user_id=current_user.id,
            message=f"Создано государство {nation.title}.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        self.session.refresh(nation)
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def update_my_nation(self, current_user: User, payload: NationUpdateRequest) -> NationRead:
        nation = self._require_manageable_nation(current_user)

        if payload.slug is not None:
            slug = self._normalize_slug(payload.slug)
            if slug != nation.slug and self._slug_exists(slug):
                raise NationConflictError("nation slug is already taken")
            nation.slug = slug

        if payload.title is not None:
            nation.title = payload.title.strip()

        if payload.tag is not None:
            nation.tag = payload.tag.strip().upper()

        if payload.short_description is not None:
            nation.short_description = payload.short_description.strip() or None

        if payload.description is not None:
            nation.description = payload.description.strip() or None

        if payload.accent_color is not None:
            nation.accent_color = payload.accent_color.strip() or None

        if payload.recruitment_policy is not None:
            nation.recruitment_policy = payload.recruitment_policy

        if payload.is_public is not None:
            nation.is_public = payload.is_public

        self.activity_service.record(
            nation_id=nation.id,
            event_type="nation_updated",
            actor_user_id=current_user.id,
            message=f"Обновлено государство {nation.title}.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def leave_my_nation(self, current_user: User) -> NationActionResponse:
        nation = self._find_nation_for_user(current_user.id)
        if nation is None:
            raise NationPermissionError("user is not in a nation")

        membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        if membership is None:
            raise NationPermissionError("user is not in a nation")

        if membership.role == "leader":
            raise NationPermissionError("leader cannot leave nation without leadership transfer")

        self.session.delete(membership)

        self.activity_service.record(
            nation_id=nation.id,
            event_type="member_left",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            message="Участник покинул государство.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return NationActionResponse(
            message="Ты вышел из государства.",
            nation=self._build_read(nation, viewer=current_user),
        )

    def join(self, current_user: User, slug: str, payload: NationJoinRequestCreate) -> NationJoinActionResponse:
        if self._find_nation_for_user(current_user.id) is not None:
            raise NationConflictError("user is already in a nation")

        nation = self._get_nation_by_slug(slug)
        if nation is None or not nation.is_public:
            raise NationNotFoundError("nation was not found")

        existing_request = self.session.execute(
            select(NationJoinRequest).where(
                NationJoinRequest.nation_id == nation.id,
                NationJoinRequest.user_id == current_user.id,
                NationJoinRequest.status == "pending",
            )
        ).scalar_one_or_none()

        if existing_request is not None:
            raise NationConflictError("join request already exists")

        if nation.recruitment_policy == "invite_only":
            raise NationPermissionError("nation accepts members by invite only")

        if nation.recruitment_policy == "open":
            self.session.add(
                NationMember(
                    server_id=self.server_id,
                    nation_id=nation.id,
                    user_id=current_user.id,
                    role="member",
                )
            )
            self.activity_service.record(
                nation_id=nation.id,
                event_type="member_joined",
                actor_user_id=current_user.id,
                target_user_id=current_user.id,
                message="Новый участник вступил в государство.",
                metadata={"nation_slug": nation.slug},
            )
            self.session.commit()
            nation = self._get_nation_by_slug(nation.slug)
            return NationJoinActionResponse(
                message="Ты вступил в государство.",
                nation=self._build_read(nation, viewer=current_user),
            )

        join_request = NationJoinRequest(
            server_id=self.server_id,
            nation_id=nation.id,
            user_id=current_user.id,
            message=(payload.message or "").strip() or None,
            status="pending",
        )
        self.session.add(join_request)

        self.activity_service.record(
            nation_id=nation.id,
            event_type="join_requested",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            message="Подана заявка на вступление.",
            metadata={"nation_slug": nation.slug, "message": join_request.message},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return NationJoinActionResponse(
            message="Заявка на вступление отправлена.",
            nation=self._build_read(nation, viewer=current_user),
        )

    def approve_request(self, current_user: User, slug: str, request_id: UUID) -> NationRead:
        nation = self._require_manageable_nation(current_user)
        if nation.slug != slug:
            raise NationNotFoundError("nation was not found")

        join_request = self.session.execute(
            select(NationJoinRequest)
            .where(
                NationJoinRequest.id == request_id,
                NationJoinRequest.nation_id == nation.id,
                NationJoinRequest.status == "pending",
            )
        ).scalar_one_or_none()

        if join_request is None:
            raise NationNotFoundError("join request was not found")

        if self._find_nation_for_user(join_request.user_id) is not None:
            raise NationConflictError("target user is already in a nation")

        join_request.status = "approved"
        join_request.reviewed_by_user_id = current_user.id

        self.session.add(
            NationMember(
                server_id=self.server_id,
                nation_id=nation.id,
                user_id=join_request.user_id,
                role="member",
            )
        )

        self.activity_service.record(
            nation_id=nation.id,
            event_type="join_approved",
            actor_user_id=current_user.id,
            target_user_id=join_request.user_id,
            message="Заявка на вступление одобрена.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def reject_request(self, current_user: User, slug: str, request_id: UUID) -> NationRead:
        nation = self._require_manageable_nation(current_user)
        if nation.slug != slug:
            raise NationNotFoundError("nation was not found")

        join_request = self.session.execute(
            select(NationJoinRequest)
            .where(
                NationJoinRequest.id == request_id,
                NationJoinRequest.nation_id == nation.id,
                NationJoinRequest.status == "pending",
            )
        ).scalar_one_or_none()

        if join_request is None:
            raise NationNotFoundError("join request was not found")

        join_request.status = "rejected"
        join_request.reviewed_by_user_id = current_user.id

        self.activity_service.record(
            nation_id=nation.id,
            event_type="join_rejected",
            actor_user_id=current_user.id,
            target_user_id=join_request.user_id,
            message="Заявка на вступление отклонена.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def update_member_role(
        self,
        current_user: User,
        slug: str,
        target_user_id: UUID,
        payload: NationMemberRoleUpdateRequest,
    ) -> NationRead:
        nation = self._require_manageable_nation(current_user)
        if nation.slug != slug:
            raise NationNotFoundError("nation was not found")

        current_membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        target_membership = next((item for item in nation.members if item.user_id == target_user_id), None)

        if current_membership is None or target_membership is None:
            raise NationNotFoundError("nation member was not found")

        if target_membership.role == "leader":
            raise NationPermissionError("leader role cannot be edited")

        if current_membership.role != "leader" and target_membership.role == "officer":
            raise NationPermissionError("only leader can demote officers")

        target_membership.role = payload.role

        self.activity_service.record(
            nation_id=nation.id,
            event_type="member_role_updated",
            actor_user_id=current_user.id,
            target_user_id=target_user_id,
            message="Роль участника изменена.",
            metadata={"role": payload.role, "nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def update_member_prefix(
        self,
        current_user: User,
        slug: str,
        target_user_id: UUID,
        payload: NationMemberPrefixUpdateRequest,
    ) -> NationRead:
        nation = self._require_manageable_nation(current_user)
        if nation.slug != slug:
            raise NationNotFoundError("nation was not found")

        current_membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        target_membership = next((item for item in nation.members if item.user_id == target_user_id), None)

        if current_membership is None or target_membership is None:
            raise NationNotFoundError("nation member was not found")

        if target_membership.role == "leader" and current_membership.role != "leader":
            raise NationPermissionError("only leader can change leader prefix")

        if current_membership.role == "officer" and target_membership.role == "officer":
            raise NationPermissionError("officers cannot change other officers' prefix")

        target_membership.custom_prefix = payload.custom_prefix

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def remove_member(self, current_user: User, slug: str, target_user_id: UUID) -> NationRead:
        nation = self._require_manageable_nation(current_user)
        if nation.slug != slug:
            raise NationNotFoundError("nation was not found")

        current_membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        target_membership = next((item for item in nation.members if item.user_id == target_user_id), None)

        if current_membership is None or target_membership is None:
            raise NationNotFoundError("nation member was not found")

        if target_membership.role == "leader":
            raise NationPermissionError("leader cannot be removed")

        if current_membership.role != "leader" and target_membership.role == "officer":
            raise NationPermissionError("only leader can remove officers")

        self.session.delete(target_membership)

        self.activity_service.record(
            nation_id=nation.id,
            event_type="member_removed",
            actor_user_id=current_user.id,
            target_user_id=target_user_id,
            message="Участник исключён из государства.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def transfer_leadership(
        self,
        current_user: User,
        slug: str,
        payload: NationTransferLeadershipRequest,
    ) -> NationRead:
        nation = self._require_manageable_nation(current_user)
        if nation.slug != slug:
            raise NationNotFoundError("nation was not found")

        current_membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        target_membership = next((item for item in nation.members if item.user_id == payload.target_user_id), None)

        if current_membership is None or current_membership.role != "leader":
            raise NationPermissionError("only leader can transfer leadership")

        if target_membership is None:
            raise NationNotFoundError("target nation member was not found")

        current_membership.role = "officer"
        target_membership.role = "leader"
        nation.leader_user_id = payload.target_user_id

        self.activity_service.record(
            nation_id=nation.id,
            event_type="leadership_transferred",
            actor_user_id=current_user.id,
            target_user_id=payload.target_user_id,
            message="Лидерство передано другому участнику.",
            metadata={"nation_slug": nation.slug},
        )

        self.session.commit()
        nation = self._get_nation_by_slug(nation.slug)
        return self._build_read(nation, viewer=current_user)

    def disband_my_nation(self, current_user: User) -> NationDisbandResponse:
        nation = self._find_nation_for_user(current_user.id)
        if nation is None:
            raise NationPermissionError("user is not in a nation")

        membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        if membership is None or membership.role != "leader":
            raise NationPermissionError("only leader can disband nation")

        founder_alliance = self.session.execute(
            select(Alliance).where(Alliance.founder_nation_id == nation.id)
        ).scalar_one_or_none()

        if founder_alliance is not None:
            other_members = self.session.execute(
                select(AllianceMember).where(
                    AllianceMember.alliance_id == founder_alliance.id,
                    AllianceMember.nation_id != nation.id,
                )
            ).scalars().first()

            if other_members is not None:
                raise NationPermissionError("nation is founder of alliance with other members")

            self.session.delete(founder_alliance)
            self.session.flush()

        self.session.delete(nation)
        self.session.commit()

        return NationDisbandResponse(message="Nation disbanded successfully.")

    def _build_read(self, nation: Nation, viewer: User | None = None) -> NationRead:
        viewer_membership = None
        viewer_request_status = None

        if viewer is not None:
            viewer_membership = next((item for item in nation.members if item.user_id == viewer.id), None)
            viewer_request = next(
                (
                    item
                    for item in nation.join_requests
                    if item.user_id == viewer.id and item.status == "pending"
                ),
                None,
            )
            viewer_request_status = viewer_request.status if viewer_request else None

        alliance_summary = self._build_alliance_summary(nation, viewer)

        return NationRead(
            id=nation.id,
            slug=nation.slug,
            title=nation.title,
            tag=nation.tag,
            short_description=nation.short_description,
            description=nation.description,
            accent_color=nation.accent_color,
            recruitment_policy=nation.recruitment_policy,
            is_public=nation.is_public,
            leader_user_id=nation.leader_user_id,
            capital_x=nation.capital_x,
            capital_z=nation.capital_z,
            capital_world=nation.capital_world,
            assets=NationAssetsRead(
                icon_url=nation.icon_url,
                icon_preview_url=nation.icon_preview_url,
                banner_url=nation.banner_url,
                banner_preview_url=nation.banner_preview_url,
                background_url=nation.background_url,
                background_preview_url=nation.background_preview_url,
            ),
            stats=NationStatsRead(
                members_count=len(nation.members),
                pending_requests_count=sum(1 for item in nation.join_requests if item.status == "pending"),
            ),
            alliance_summary=alliance_summary,
            viewer_role=viewer_membership.role if viewer_membership else None,
            viewer_is_member=viewer_membership is not None,
            viewer_can_manage=viewer_membership is not None and viewer_membership.role in {"leader", "officer"},
            viewer_request_status=viewer_request_status,
            members=[
                NationMemberRead(
                    user_id=item.user_id,
                    site_login=item.user.site_login if item.user else "unknown",
                    minecraft_nickname=item.user.player_account.minecraft_nickname if item.user and item.user.player_account else None,
                    role=item.role,
                    custom_prefix=item.custom_prefix,
                    created_at=item.created_at,
                )
                for item in sorted(
                    nation.members,
                    key=lambda x: (
                        0 if x.role == "leader" else 1 if x.role == "officer" else 2,
                        x.created_at,
                    ),
                )
            ],
            join_requests=[
                NationJoinRequestRead(
                    id=item.id,
                    user_id=item.user_id,
                    site_login=item.user.site_login if item.user else "unknown",
                    minecraft_nickname=item.user.player_account.minecraft_nickname if item.user and item.user.player_account else None,
                    message=item.message,
                    status=item.status,
                    created_at=item.created_at,
                )
                for item in sorted(
                    [req for req in nation.join_requests if req.status == "pending"],
                    key=lambda x: x.created_at,
                )
                if viewer_membership is not None and viewer_membership.role in {"leader", "officer"}
            ],
            created_at=nation.created_at,
            updated_at=nation.updated_at,
        )

    def _build_alliance_summary(self, nation: Nation, viewer: User | None = None) -> NationAllianceSummaryRead | None:
        alliance_member = self.session.execute(
            select(AllianceMember).where(AllianceMember.nation_id == nation.id)
        ).scalar_one_or_none()

        if alliance_member is None:
            return None

        alliance = self.session.execute(
            select(Alliance)
            .options(joinedload(Alliance.members))
            .where(Alliance.id == alliance_member.alliance_id)
        ).unique().scalar_one_or_none()

        if alliance is None:
            return None

        member_nation_ids = [item.nation_id for item in alliance.members]
        member_nations = (
            self.session.execute(select(Nation).where(Nation.id.in_(member_nation_ids))).scalars().all()
            if member_nation_ids
            else []
        )
        nation_lookup = {item.id: item for item in member_nations}

        viewer_nation = self._find_nation_for_user(viewer.id) if viewer is not None else None
        viewer_nation_id = viewer_nation.id if viewer_nation is not None else None

        serialized_members = []
        for item in alliance.members:
            member_nation = nation_lookup.get(item.nation_id)
            if member_nation is None:
                continue

            serialized_members.append(
                NationAllianceMemberSummaryRead(
                    nation_id=member_nation.id,
                    slug=member_nation.slug,
                    title=member_nation.title,
                    tag=member_nation.tag,
                    accent_color=member_nation.accent_color,
                    icon_url=member_nation.icon_url,
                    icon_preview_url=member_nation.icon_preview_url,
                )
            )

        founder_member = next((item for item in alliance.members if item.nation_id == alliance.founder_nation_id), None)

        return NationAllianceSummaryRead(
            id=alliance.id,
            slug=alliance.slug,
            title=alliance.title,
            tag=alliance.tag,
            alliance_type=alliance.alliance_type,
            description=alliance.description,
            transfer_fee_percent=float(alliance.transfer_fee_percent or 0),
            treasury_balance=float(alliance.treasury_balance or 0),
            allow_internal_transfers=bool(alliance.allow_internal_transfers),
            allow_joint_defense=bool(alliance.allow_joint_defense),
            allow_trade_bonus=bool(alliance.allow_trade_bonus),
            allow_pvp_protection=bool(alliance.allow_pvp_protection),
            members_count=len(serialized_members),
            viewer_nation_is_member=viewer_nation_id is not None and any(item.nation_id == viewer_nation_id for item in alliance.members),
            viewer_nation_is_founder=viewer_nation_id is not None and founder_member is not None and founder_member.nation_id == viewer_nation_id,
            members=serialized_members,
        )

    def _find_nation_for_user(self, user_id: UUID) -> Nation | None:
        return (
            self.session.execute(
                select(Nation)
                .join(NationMember, NationMember.nation_id == Nation.id)
                .options(
                    joinedload(Nation.members).joinedload(NationMember.user).joinedload(User.player_account),
                    joinedload(Nation.join_requests).joinedload(NationJoinRequest.user).joinedload(User.player_account),
                )
                .where(NationMember.user_id == user_id)
                .where(Nation.server_id == self.server_id)
            )
            .unique()
            .scalar_one_or_none()
        )

    def _get_nation_by_slug(self, slug: str) -> Nation | None:
        normalized = self._normalize_slug(slug)
        return (
            self.session.execute(
                select(Nation)
                .options(
                    joinedload(Nation.members).joinedload(NationMember.user).joinedload(User.player_account),
                    joinedload(Nation.join_requests).joinedload(NationJoinRequest.user).joinedload(User.player_account),
                )
                .where(Nation.slug == normalized)
                .where(Nation.server_id == self.server_id)
            )
            .unique()
            .scalar_one_or_none()
        )


    def _require_min_balance_for_create(self, current_user: User) -> None:
        current_balance = self._get_latest_balance_for_user(current_user.id)
        if current_balance < MIN_NATION_CREATE_BALANCE:
            raise NationValidationError(
                "not enough balance to create nation"
            )

    def _get_latest_balance_for_user(self, user_id: UUID) -> Decimal:
        snapshot = (
            self.session.execute(
                select(NationMemberStatSnapshot)
                .where(
                    NationMemberStatSnapshot.user_id == user_id,
                    NationMemberStatSnapshot.server_id == self.server_id,
                )
                .order_by(NationMemberStatSnapshot.last_synced_at.desc(), NationMemberStatSnapshot.created_at.desc())
            )
            .scalars()
            .first()
        )
        if snapshot is not None:
            return Decimal(str(getattr(snapshot, "current_balance", 0) or 0))

        cache = self.session.execute(
            select(PlayerStatCache).where(
                PlayerStatCache.user_id == user_id,
                PlayerStatCache.server_id == self.server_id,
            )
        ).scalar_one_or_none()
        if cache is not None:
            return Decimal(str(getattr(cache, "current_balance", 0) or 0))

        return Decimal("0")

    def _slug_exists(self, slug: str) -> bool:
        return self.session.execute(
            select(Nation.id).where(
                Nation.slug == slug,
                Nation.server_id == self.server_id,
            )
        ).scalar_one_or_none() is not None

    def _normalize_slug(self, slug: str) -> str:
        normalized = SLUG_CLEANUP_PATTERN.sub("-", (slug or "").strip().lower()).strip("-")
        if len(normalized) < 3:
            raise NationValidationError("nation slug is too short")
        if len(normalized) > 64:
            normalized = normalized[:64].strip("-")
        if len(normalized) < 3:
            raise NationValidationError("nation slug is too short")
        return normalized

    def _can_manage(self, nation: Nation, viewer: User | None) -> bool:
        if viewer is None:
            return False
        membership = next((item for item in nation.members if item.user_id == viewer.id), None)
        return membership is not None and membership.role in {"leader", "officer"}

    def _require_manageable_nation(self, current_user: User) -> Nation:
        nation = self._find_nation_for_user(current_user.id)
        if nation is None:
            raise NationPermissionError("user is not in a nation")

        membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        if membership is None or membership.role not in {"leader", "officer"}:
            raise NationPermissionError("not enough permissions to manage nation")

        return nation
