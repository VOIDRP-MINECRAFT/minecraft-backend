"""Weekly top-nation rewards.

Ranks a server's nations and pays the top few a prize into their treasury, at
most once per :data:`SEASON_PERIOD_DAYS`. Idempotent by period (skips if any
``season_reward`` transaction exists within the window), so the plugin can tick
it on a short timer safely.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.services.nation_activity_service import NationActivityService

MONEY_QUANT = Decimal("0.01")
SEASON_PERIOD_DAYS = 7

# rank -> prize credited to the nation treasury
REWARDS: dict[int, Decimal] = {
    1: Decimal("250000"),
    2: Decimal("100000"),
    3: Decimal("50000"),
}


class NationSeasonService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id
        self.activity = NationActivityService(session, server_id)

    def _as_money(self, value) -> Decimal:
        return Decimal(str(value or 0)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    def award_weekly_top_nations(self) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=SEASON_PERIOD_DAYS)

        last_at = self.session.execute(
            select(NationTreasuryTransaction.created_at)
            .where(
                NationTreasuryTransaction.server_id == self.server_id,
                NationTreasuryTransaction.transaction_type == "season_reward",
            )
            .order_by(NationTreasuryTransaction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_at is not None and last_at > cutoff:
            return {"awarded": [], "skipped": True}

        ranked = self.session.execute(
            select(NationStat, Nation)
            .join(Nation, Nation.id == NationStat.nation_id)
            .where(Nation.server_id == self.server_id, Nation.is_technical.is_(False))
            .order_by(
                NationStat.prestige_score.desc(),
                NationStat.total_playtime_minutes.desc(),
            )
            .limit(len(REWARDS))
        ).all()

        winners: list[dict] = []
        rank = 0
        for stat, nation in ranked:
            # Only reward nations that actually did something this season.
            if stat.prestige_score <= 0 and stat.total_playtime_minutes <= 0:
                continue
            rank += 1
            prize = REWARDS.get(rank)
            if prize is None:
                break

            stat.treasury_balance = self._as_money(self._as_money(stat.treasury_balance) + prize)
            self.session.add(
                NationTreasuryTransaction(
                    server_id=self.server_id,
                    transaction_type="season_reward",
                    nation_id=nation.id,
                    created_by_user_id=None,
                    gross_amount=prize,
                    fee_amount=Decimal("0.00"),
                    net_amount=prize,
                    comment=f"Награда сезона за {rank}-е место",
                    metadata_json={
                        "rank": rank,
                        "prestige_score": stat.prestige_score,
                        "nation_slug": nation.slug,
                    },
                )
            )
            self.activity.record(
                nation_id=nation.id,
                event_type="nation_season_reward",
                message=f"Государство заняло {rank}-е место сезона и получило +{prize} в казну.",
                metadata={"rank": rank, "prize": str(prize)},
            )
            winners.append(
                {
                    "rank": rank,
                    "nation_slug": nation.slug,
                    "nation_title": nation.title,
                    "prize": float(prize),
                }
            )

        # Only commit (and mark the period consumed) if someone was actually paid.
        if winners:
            self.session.commit()
        else:
            self.session.rollback()

        return {"awarded": winners, "skipped": False}
