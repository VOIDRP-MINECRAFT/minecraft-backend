from __future__ import annotations

import hmac
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.tiktok import TikTokCampaign, TikTokClickReward
from apps.api.app.schemas.tiktok import (
    TikTokCampaignResponse,
    TikTokPendingReward,
    TikTokPendingRewardsResponse,
)


def sign_click(secret: str, campaign_id: str, minecraft_uuid: str) -> str:
    """Short HMAC tag that prevents forging click links for arbitrary UUIDs.

    Must match the plugin's computation exactly:
    HMAC-SHA256(secret, "<campaign_id>:<uuid>") hex, first 16 chars.
    """
    msg = f"{campaign_id}:{minecraft_uuid}".encode()
    return hmac.new(secret.encode(), msg, sha256).hexdigest()[:16]


class TikTokService:
    """Server-scoped TikTok campaign + click-reward logic."""

    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def create_campaign(self, video_url: str, deactivate_previous: bool) -> TikTokCampaignResponse:
        if deactivate_previous:
            self.session.execute(
                update(TikTokCampaign)
                .where(
                    TikTokCampaign.server_id == self.server_id,
                    TikTokCampaign.is_active.is_(True),
                )
                .values(is_active=False)
            )

        campaign = TikTokCampaign(
            server_id=self.server_id,
            video_url=video_url.strip(),
            is_active=True,
        )
        self.session.add(campaign)
        self.session.flush()  # populate campaign.id

        settings = get_settings()
        base = settings.public_api_base_url.rstrip("/")
        click_base = f"{base}/api/v1/tiktok/c/{campaign.id}"
        return TikTokCampaignResponse(
            campaign_id=str(campaign.id),
            video_url=campaign.video_url,
            click_base=click_base,
        )

    def list_pending(self) -> TikTokPendingRewardsResponse:
        rows = self.session.scalars(
            select(TikTokClickReward)
            .where(
                TikTokClickReward.server_id == self.server_id,
                TikTokClickReward.delivered.is_(False),
            )
            .order_by(TikTokClickReward.created_at.asc())
            .limit(500)
        ).all()
        rewards = [
            TikTokPendingReward(
                reward_id=str(r.id),
                campaign_id=str(r.campaign_id),
                minecraft_uuid=r.minecraft_uuid,
                minecraft_nickname=r.minecraft_nickname,
            )
            for r in rows
        ]
        return TikTokPendingRewardsResponse(rewards=rewards)

    def ack(self, ids: list[str]) -> int:
        if not ids:
            return 0
        uuids: list[UUID] = []
        for raw in ids:
            try:
                uuids.append(UUID(raw))
            except (ValueError, TypeError):
                continue
        if not uuids:
            return 0
        result = self.session.execute(
            update(TikTokClickReward)
            .where(
                TikTokClickReward.server_id == self.server_id,
                TikTokClickReward.id.in_(uuids),
                TikTokClickReward.delivered.is_(False),
            )
            .values(delivered=True, delivered_at=datetime.now(timezone.utc))
        )
        return int(result.rowcount or 0)


def resolve_and_record_click(
    session: Session,
    campaign_id: str,
    minecraft_uuid: str,
    minecraft_nickname: str | None,
    sig: str,
) -> str | None:
    """Public (unauthenticated) click handler.

    Verifies the HMAC signature against the campaign's server secret, records a
    one-time pending reward for the player, and returns the video URL to redirect
    to. Returns ``None`` if the campaign is missing/inactive or the signature is
    invalid (caller should redirect to a safe fallback).
    """
    try:
        cid = UUID(campaign_id)
    except (ValueError, TypeError):
        return None

    campaign = session.get(TikTokCampaign, cid)
    if campaign is None or not campaign.is_active:
        # Still allow redirect if the campaign exists but is inactive? No — an
        # inactive/old link should not mint rewards, but we can still send the
        # user to the video if it exists.
        if campaign is not None:
            _maybe_redirect_only = campaign.video_url
        else:
            return None
        # Verify signature even for inactive so we don't leak; but no reward.
        server = session.get(GameServer, campaign.server_id)
        if server is None:
            return None
        expected = sign_click(server.game_auth_secret, campaign_id, minecraft_uuid)
        if not hmac.compare_digest(expected, sig or ""):
            return None
        return _maybe_redirect_only

    server = session.get(GameServer, campaign.server_id)
    if server is None:
        return None

    expected = sign_click(server.game_auth_secret, campaign_id, minecraft_uuid)
    if not hmac.compare_digest(expected, sig or ""):
        return None

    # Record a one-time pending reward (unique on campaign_id + uuid).
    reward = TikTokClickReward(
        server_id=campaign.server_id,
        campaign_id=campaign.id,
        minecraft_uuid=minecraft_uuid,
        minecraft_nickname=(minecraft_nickname or None),
    )
    session.add(reward)
    try:
        session.flush()
        session.commit()
    except IntegrityError:
        # Player already clicked this campaign — that's fine, just redirect.
        session.rollback()

    return campaign.video_url
