from __future__ import annotations

from pydantic import BaseModel, Field


class TikTokCampaignCreateRequest(BaseModel):
    video_url: str = Field(..., min_length=5, max_length=500)
    # Deactivate the server's previous active campaigns (only the newest video
    # keeps rewarding). Defaults to True — one live campaign at a time.
    deactivate_previous: bool = True


class TikTokCampaignResponse(BaseModel):
    campaign_id: str
    video_url: str
    # Full base URL the plugin appends ``/{uuid}/{sig}`` to for each player.
    click_base: str


class TikTokPendingReward(BaseModel):
    reward_id: str
    campaign_id: str
    minecraft_uuid: str
    minecraft_nickname: str | None = None


class TikTokPendingRewardsResponse(BaseModel):
    rewards: list[TikTokPendingReward] = Field(default_factory=list)


class TikTokRewardAckRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class TikTokRewardAckResponse(BaseModel):
    acknowledged: int
