from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class ReferralCodeRead(BaseModel):
    code: str
    invite_url: str


class ReferralLinkItemRead(BaseModel):
    site_login: str
    minecraft_nickname: str
    status: str
    created_at: datetime
    qualified_at: datetime | None = None


class ReferralRewardPeriodRead(BaseModel):
    referral_rank: str
    starts_at: datetime
    expires_at: datetime
    source_qualified_referrals: int
    reward_state: str


class ReferralTotalsRead(BaseModel):
    pending: int
    qualified: int
    current_rank: str | None = None


class ReferralDashboardResponse(BaseModel):
    my_code: ReferralCodeRead
    totals: ReferralTotalsRead
    current_reward: ReferralRewardPeriodRead | None = None
    recent_links: list[ReferralLinkItemRead]


class ReferralCodePreviewResponse(BaseModel):
    code: str
    inviter_site_login: str
    inviter_minecraft_nickname: str
    inviter_display_name: str | None = None


class RegenerateReferralCodeResponse(BaseModel):
    message: str
    my_code: ReferralCodeRead