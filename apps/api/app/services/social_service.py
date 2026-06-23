from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models.player_follow import PlayerFollow
from apps.api.app.models.player_public_profile import PlayerPublicProfile
from apps.api.app.models.user import User
from apps.api.app.schemas.social import FollowActionResponse, SocialListResponse, SocialProfileCard


class SocialNotFoundError(Exception):
    pass


class SocialValidationError(Exception):
    pass


class SocialService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def follow(self, *, current_user: User, target_slug: str) -> FollowActionResponse:
        target_profile = self._get_target_profile(target_slug)
        if target_profile.user is None:
            raise SocialNotFoundError("target profile was not found")

        if target_profile.user_id == current_user.id:
            raise SocialValidationError("you cannot follow yourself")

        existing = self.session.execute(
            select(PlayerFollow).where(
                PlayerFollow.follower_user_id == current_user.id,
                PlayerFollow.target_user_id == target_profile.user_id,
            )
        ).scalar_one_or_none()

        if existing is None:
            self.session.add(
                PlayerFollow(
                    follower_user_id=current_user.id,
                    target_user_id=target_profile.user_id,
                )
            )
            self.session.commit()

        is_friend = self._follow_exists(target_profile.user_id, current_user.id)
        return FollowActionResponse(
            message="Follow created successfully.",
            is_following=True,
            is_friend=is_friend,
        )

    def unfollow(self, *, current_user: User, target_slug: str) -> FollowActionResponse:
        target_profile = self._get_target_profile(target_slug)
        existing = self.session.execute(
            select(PlayerFollow).where(
                PlayerFollow.follower_user_id == current_user.id,
                PlayerFollow.target_user_id == target_profile.user_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            self.session.delete(existing)
            self.session.commit()

        is_friend = False
        return FollowActionResponse(
            message="Follow removed successfully.",
            is_following=False,
            is_friend=is_friend,
        )

    def list_followers(self, *, current_user: User) -> SocialListResponse:
        rows = self.session.execute(
            select(PlayerFollow)
            .options(
                joinedload(PlayerFollow.follower).joinedload(User.player_account),
                joinedload(PlayerFollow.follower).joinedload(User.public_profile),
            )
            .where(PlayerFollow.target_user_id == current_user.id)
            .order_by(PlayerFollow.created_at.desc())
        ).scalars().all()

        items = [self._build_card(item.follower, current_user.id) for item in rows if item.follower is not None]
        return SocialListResponse(total=len(items), items=items)

    def list_following(self, *, current_user: User) -> SocialListResponse:
        rows = self.session.execute(
            select(PlayerFollow)
            .options(
                joinedload(PlayerFollow.target).joinedload(User.player_account),
                joinedload(PlayerFollow.target).joinedload(User.public_profile),
            )
            .where(PlayerFollow.follower_user_id == current_user.id)
            .order_by(PlayerFollow.created_at.desc())
        ).scalars().all()

        items = [self._build_card(item.target, current_user.id) for item in rows if item.target is not None]
        return SocialListResponse(total=len(items), items=items)

    def list_friends(self, *, current_user: User) -> SocialListResponse:
        rows = self.session.execute(
            select(PlayerFollow)
            .options(
                joinedload(PlayerFollow.target).joinedload(User.player_account),
                joinedload(PlayerFollow.target).joinedload(User.public_profile),
            )
            .where(
                PlayerFollow.follower_user_id == current_user.id,
                PlayerFollow.target_user_id.in_(
                    select(PlayerFollow.follower_user_id).where(PlayerFollow.target_user_id == current_user.id)
                ),
            )
            .order_by(PlayerFollow.created_at.desc())
        ).scalars().all()

        items = [self._build_card(item.target, current_user.id, force_friend=True) for item in rows if item.target is not None]
        return SocialListResponse(total=len(items), items=items)

    def _get_target_profile(self, slug: str) -> PlayerPublicProfile:
        profile = self.session.execute(
            select(PlayerPublicProfile)
            .options(joinedload(PlayerPublicProfile.user).joinedload(User.player_account))
            .where(PlayerPublicProfile.slug == slug)
        ).unique().scalar_one_or_none()

        if profile is None:
            raise SocialNotFoundError("target profile was not found")
        return profile

    def _build_card(self, user: User, viewer_user_id, force_friend: bool = False) -> SocialProfileCard:
        profile = user.public_profile
        avatar_url = None
        if profile is not None and profile.avatar_asset is not None:
            variants = profile.avatar_asset.variants_json or {}
            if isinstance(variants, dict):
                preview = variants.get("preview") or variants.get("full")
                if isinstance(preview, dict):
                    avatar_url = preview.get("url")

        is_friend = force_friend or self._follow_exists(user.id, viewer_user_id)
        return SocialProfileCard(
            slug=profile.slug if profile is not None else user.site_login.lower(),
            site_login=user.site_login,
            minecraft_nickname=user.player_account.minecraft_nickname if user.player_account else user.site_login,
            display_name=profile.display_name if profile is not None else None,
            avatar_url=avatar_url,
            is_friend=is_friend,
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