from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.core.security import utc_now
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_follow import PlayerFollow
from apps.api.app.models.player_public_profile import PlayerPublicProfile
from apps.api.app.models.referral_link import ReferralLink
from apps.api.app.models.referral_reward_period import ReferralRewardPeriod
from apps.api.app.models.user import User
from apps.api.app.schemas.profile import (
    PublicProfileAssetsRead,
    PublicProfileNationSummaryRead,
    PublicProfileRead,
    PublicProfileStatsRead,
    PublicProfileViewerStateRead,
    UpdatePublicProfileRequest,
)

SLUG_CLEANUP_PATTERN = re.compile(r"[^a-z0-9._-]+")


class PublicProfileNotFoundError(Exception):
    pass


class PublicProfileConflictError(Exception):
    pass


@dataclass(slots=True)
class PublicProfileContext:
    user: User
    profile: PlayerPublicProfile


class PublicProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_me(self, current_user: User) -> PublicProfileRead:
        context = self._get_or_create_context_for_user(current_user)
        return self._build_read(context=context, viewer=current_user)

    def update_me(
        self,
        current_user: User,
        payload: UpdatePublicProfileRequest,
    ) -> PublicProfileRead:
        context = self._get_or_create_context_for_user(current_user)
        profile = context.profile
        fields_set = getattr(payload, "model_fields_set", set())

        if "slug" in fields_set and payload.slug is not None and payload.slug != profile.slug:
            existing = self.session.execute(
                select(PlayerPublicProfile).where(PlayerPublicProfile.slug == payload.slug)
            ).scalar_one_or_none()
            if existing is not None and existing.user_id != current_user.id:
                raise PublicProfileConflictError("slug is already taken")
            profile.slug = payload.slug

        if "display_name" in fields_set:
            profile.display_name = payload.display_name

        if "bio" in fields_set:
            profile.bio = payload.bio

        if "status_text" in fields_set:
            profile.status_text = payload.status_text

        if "theme_mode" in fields_set and payload.theme_mode is not None:
            profile.theme_mode = payload.theme_mode

        if "accent_color" in fields_set:
            profile.accent_color = payload.accent_color

        if "is_public" in fields_set and payload.is_public is not None:
            profile.is_public = payload.is_public

        if (
            "allow_followers_list_public" in fields_set
            and payload.allow_followers_list_public is not None
        ):
            profile.allow_followers_list_public = payload.allow_followers_list_public

        if (
            "allow_friends_list_public" in fields_set
            and payload.allow_friends_list_public is not None
        ):
            profile.allow_friends_list_public = payload.allow_friends_list_public

        self.session.commit()
        self.session.refresh(profile)

        return self._build_read(context=context, viewer=current_user)

    def get_by_slug(self, slug: str, viewer: User | None = None) -> PublicProfileRead:
        from apps.api.app.models.player_account import PlayerAccount

        _opts = [
            joinedload(PlayerPublicProfile.user).joinedload(User.player_account),
            joinedload(PlayerPublicProfile.user).joinedload(User.public_profile),
            joinedload(PlayerPublicProfile.avatar_asset),
            joinedload(PlayerPublicProfile.banner_asset),
            joinedload(PlayerPublicProfile.background_asset),
        ]

        profile = self.session.execute(
            select(PlayerPublicProfile).options(*_opts).where(PlayerPublicProfile.slug == slug)
        ).unique().scalar_one_or_none()

        if profile is None:
            # Fallback: look up by minecraft_nickname_normalized so that
            # /u/<MinecraftNick> works from leaderboard links.
            profile = self.session.execute(
                select(PlayerPublicProfile)
                .join(PlayerPublicProfile.user)
                .join(User.player_account)
                .options(*_opts)
                .where(func.lower(PlayerAccount.minecraft_nickname) == slug.lower())
            ).unique().scalar_one_or_none()

        if profile is None or profile.user is None or profile.user.player_account is None:
            raise PublicProfileNotFoundError("profile was not found")

        if not profile.is_public and (viewer is None or viewer.id != profile.user_id):
            raise PublicProfileNotFoundError("profile was not found")

        return self._build_read(
            context=PublicProfileContext(user=profile.user, profile=profile),
            viewer=viewer,
        )

    def ensure_profile_for_user(self, user: User) -> PlayerPublicProfile:
        return self._get_or_create_context_for_user(user).profile

    def _get_or_create_context_for_user(self, user: User) -> PublicProfileContext:
        profile = self.session.execute(
            select(PlayerPublicProfile)
            .options(
                joinedload(PlayerPublicProfile.user).joinedload(User.player_account),
                joinedload(PlayerPublicProfile.avatar_asset),
                joinedload(PlayerPublicProfile.banner_asset),
                joinedload(PlayerPublicProfile.background_asset),
            )
            .where(PlayerPublicProfile.user_id == user.id)
        ).unique().scalar_one_or_none()

        if profile is None:
            profile = PlayerPublicProfile(
                user_id=user.id,
                slug=self._generate_unique_profile_slug(user.site_login),
                display_name=user.player_account.minecraft_nickname if user.player_account else user.site_login,
                bio=None,
                status_text=None,
                theme_mode="default",
                accent_color=None,
                is_public=True,
                allow_followers_list_public=True,
                allow_friends_list_public=True,
                allow_profile_comments=False,
            )
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)

        return PublicProfileContext(user=user, profile=profile)

    def _find_public_nation_for_user(self, user_id, viewer: User | None) -> Nation | None:
        nation = self.session.execute(
            select(Nation)
            .join(NationMember, NationMember.nation_id == Nation.id)
            .where(NationMember.user_id == user_id)
            .order_by(Nation.created_at.desc())
        ).scalar_one_or_none()

        if nation is None:
            return None

        if nation.is_public:
            return nation

        if viewer is not None and viewer.id == user_id:
            return nation

        return None

    def _build_nation_summary(self, nation: Nation | None) -> PublicProfileNationSummaryRead | None:
        if nation is None:
            return None

        return PublicProfileNationSummaryRead(
            id=nation.id,
            slug=nation.slug,
            title=nation.title,
            tag=nation.tag,
            short_description=nation.short_description,
            accent_color=nation.accent_color,
            icon_url=nation.icon_url,
            icon_preview_url=nation.icon_preview_url,
        )

    def _build_read(self, *, context: PublicProfileContext, viewer: User | None) -> PublicProfileRead:
        user = context.user
        profile = context.profile

        if user.player_account is None:
            raise PublicProfileNotFoundError("player account is missing")

        followers = int(
            self.session.scalar(
                select(func.count()).select_from(PlayerFollow).where(PlayerFollow.target_user_id == user.id)
            )
            or 0
        )
        following = int(
            self.session.scalar(
                select(func.count()).select_from(PlayerFollow).where(PlayerFollow.follower_user_id == user.id)
            )
            or 0
        )
        friends = int(
            self.session.scalar(
                select(func.count()).select_from(PlayerFollow).where(
                    PlayerFollow.follower_user_id == user.id,
                    PlayerFollow.target_user_id.in_(
                        select(PlayerFollow.follower_user_id).where(PlayerFollow.target_user_id == user.id)
                    ),
                )
            )
            or 0
        )

        pending_referrals = int(
            self.session.scalar(
                select(func.count()).select_from(ReferralLink).where(
                    ReferralLink.inviter_user_id == user.id,
                    ReferralLink.status == "pending",
                )
            )
            or 0
        )
        qualified_referrals = int(
            self.session.scalar(
                select(func.count()).select_from(ReferralLink).where(
                    ReferralLink.inviter_user_id == user.id,
                    ReferralLink.status == "qualified",
                )
            )
            or 0
        )

        active_reward = self.session.execute(
            select(ReferralRewardPeriod)
            .where(
                ReferralRewardPeriod.user_id == user.id,
                ReferralRewardPeriod.reward_state == "active",
                ReferralRewardPeriod.expires_at > utc_now(),
            )
            .order_by(ReferralRewardPeriod.expires_at.desc())
        ).scalar_one_or_none()

        nation_summary = self._build_nation_summary(self._find_public_nation_for_user(user.id, viewer))

        is_self = viewer is not None and viewer.id == user.id
        is_following = False
        follows_you = False
        is_friend = False

        if viewer is not None and viewer.id != user.id:
            is_following = self._follow_exists(viewer.id, user.id)
            follows_you = self._follow_exists(user.id, viewer.id)
            is_friend = is_following and follows_you

        return PublicProfileRead(
            user=user,
            player_account=user.player_account,
            slug=profile.slug,
            display_name=profile.display_name,
            bio=profile.bio,
            status_text=profile.status_text,
            theme_mode=profile.theme_mode,
            accent_color=profile.accent_color,
            is_public=profile.is_public,
            allow_followers_list_public=profile.allow_followers_list_public,
            allow_friends_list_public=profile.allow_friends_list_public,
            assets=self._build_assets(profile),
            nation=nation_summary,
            stats=PublicProfileStatsRead(
                followers=followers,
                following=following,
                friends=friends,
                pending_referrals=pending_referrals,
                qualified_referrals=qualified_referrals,
            ),
            viewer=PublicProfileViewerStateRead(
                is_self=is_self,
                is_following=is_following,
                follows_you=follows_you,
                is_friend=is_friend,
            ),
            current_referral_rank=active_reward.referral_rank if active_reward else None,
            current_referral_rank_expires_at=active_reward.expires_at if active_reward else None,
        )

    def _build_assets(self, profile: PlayerPublicProfile) -> PublicProfileAssetsRead:
        def _read_urls(asset) -> tuple[str | None, str | None]:
            if asset is None:
                return None, None

            variants = asset.variants_json or {}
            full_url = None
            preview_url = None

            if isinstance(variants, dict):
                full_item = variants.get("full")
                preview_item = variants.get("preview")

                if isinstance(full_item, dict):
                    full_url = full_item.get("url")

                if isinstance(preview_item, dict):
                    preview_url = preview_item.get("url")

            return full_url, preview_url

        avatar_url, avatar_preview_url = _read_urls(profile.avatar_asset)
        banner_url, banner_preview_url = _read_urls(profile.banner_asset)
        background_url, background_preview_url = _read_urls(profile.background_asset)

        return PublicProfileAssetsRead(
            avatar_url=avatar_url,
            avatar_preview_url=avatar_preview_url,
            banner_url=banner_url,
            banner_preview_url=banner_preview_url,
            background_url=background_url,
            background_preview_url=background_preview_url,
        )

    def _follow_exists(self, follower_user_id, target_user_id) -> bool:
        return (
            self.session.execute(
                select(PlayerFollow).where(
                    PlayerFollow.follower_user_id == follower_user_id,
                    PlayerFollow.target_user_id == target_user_id,
                )
            ).scalar_one_or_none()
            is not None
        )

    def _generate_unique_profile_slug(self, seed: str) -> str:
        base = SLUG_CLEANUP_PATTERN.sub("-", seed.strip().lower()).strip("-._")
        if not base:
            base = "player"
        base = base[:48]

        candidate = base
        suffix = 1
        while self.session.execute(
            select(PlayerPublicProfile).where(PlayerPublicProfile.slug == candidate)
        ).scalar_one_or_none() is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"[:64]

        return candidate
