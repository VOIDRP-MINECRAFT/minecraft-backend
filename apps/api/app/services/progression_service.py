from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from apps.api.app.models.player_progression import (
    PROGRESSION_TIERS,
    TIER_LABELS,
    PlayerProgression,
)
from apps.api.app.schemas.progression import (
    FullLeaderboardRead,
    LeaderboardEntryRead,
    PlayerProgressionRead,
    ProgressionTierRead,
    TierLeaderboardRead,
    TierUnlockRequest,
    TierUnlockResponse,
)


class UnknownTierError(Exception):
    pass


class ProgressionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def unlock_tier(self, payload: TierUnlockRequest) -> TierUnlockResponse:
        if payload.tier_name not in PROGRESSION_TIERS:
            raise UnknownTierError(f"Unknown tier: {payload.tier_name}")

        normalized = payload.minecraft_nickname.lower()
        existing = self.session.execute(
            select(PlayerProgression).where(
                and_(
                    PlayerProgression.minecraft_nickname_normalized == normalized,
                    PlayerProgression.tier_name == payload.tier_name,
                )
            )
        ).scalar_one_or_none()

        if existing:
            return TierUnlockResponse(accepted=True, already_had=True)

        record = PlayerProgression(
            minecraft_nickname=payload.minecraft_nickname,
            minecraft_nickname_normalized=normalized,
            minecraft_uuid=payload.minecraft_uuid,
            tier_name=payload.tier_name,
            unlocked_at=datetime.now(timezone.utc),
        )
        self.session.add(record)
        self.session.commit()
        return TierUnlockResponse(accepted=True, already_had=False)

    def get_player_progression(self, minecraft_nickname: str) -> PlayerProgressionRead | None:
        normalized = minecraft_nickname.lower()
        tiers = (
            self.session.execute(
                select(PlayerProgression)
                .where(PlayerProgression.minecraft_nickname_normalized == normalized)
                .order_by(PlayerProgression.unlocked_at)
            )
            .scalars()
            .all()
        )

        if not tiers:
            return None

        highest = None
        for tier_name in reversed(PROGRESSION_TIERS):
            if any(r.tier_name == tier_name for r in tiers):
                highest = tier_name
                break

        return PlayerProgressionRead(
            minecraft_nickname=tiers[0].minecraft_nickname,
            minecraft_uuid=tiers[0].minecraft_uuid,
            tiers=[
                ProgressionTierRead(
                    tier_name=r.tier_name,
                    tier_label=TIER_LABELS.get(r.tier_name, r.tier_name),
                    unlocked_at=r.unlocked_at,
                )
                for r in tiers
            ],
            current_tier=highest,
            current_tier_label=TIER_LABELS.get(highest) if highest else None,
        )

    def get_leaderboard(self) -> FullLeaderboardRead:
        result = []
        for tier_name in PROGRESSION_TIERS:
            records = (
                self.session.execute(
                    select(PlayerProgression)
                    .where(PlayerProgression.tier_name == tier_name)
                    .order_by(PlayerProgression.unlocked_at)
                    .limit(20)
                )
                .scalars()
                .all()
            )
            result.append(
                TierLeaderboardRead(
                    tier_name=tier_name,
                    tier_label=TIER_LABELS.get(tier_name, tier_name),
                    entries=[
                        LeaderboardEntryRead(
                            rank=i + 1,
                            minecraft_nickname=r.minecraft_nickname,
                            minecraft_uuid=r.minecraft_uuid,
                            unlocked_at=r.unlocked_at,
                        )
                        for i, r in enumerate(records)
                    ],
                )
            )
        return FullLeaderboardRead(tiers=result)
