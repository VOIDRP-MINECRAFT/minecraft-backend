"""Nation research (tech tree) service.

Spends a nation's treasury to level up code-defined research nodes and resolves
the aggregated passive effects consumed by the game plugins and other services.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_research import NationResearch
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.schemas.nation_research import (
    NationResearchEffects,
    NationResearchOverview,
    ResearchNodeState,
    ResearchPurchaseResponse,
)
from apps.api.app.services.nation_activity_service import NationActivityService
from apps.api.app.services.nation_research_catalog import CATALOG, get_node, resolve_effects

MONEY_QUANT = Decimal("0.01")

MANAGE_ROLES = {"leader", "officer"}

# "Центробанк" pays interest at most once per this many days.
INTEREST_PERIOD_DAYS = 7


class NationResearchError(Exception):
    """Base error → HTTP 400."""


class NationResearchPermissionError(Exception):
    """Actor is not allowed to manage research → HTTP 403."""


class NationResearchService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id
        self.activity = NationActivityService(session, server_id)

    # ── reads ────────────────────────────────────────────────────────────────

    def _levels_for_nation(self, nation_id: UUID) -> dict[str, int]:
        rows = self.session.execute(
            select(NationResearch.research_key, NationResearch.level).where(
                NationResearch.nation_id == nation_id,
                NationResearch.server_id == self.server_id,
            )
        ).all()
        return {key: level for key, level in rows}

    def _get_or_create_stat(self, nation_id: UUID, *, lock: bool = False) -> NationStat:
        stmt = select(NationStat).where(
            NationStat.nation_id == nation_id,
            NationStat.server_id == self.server_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        stat = self.session.execute(stmt).scalar_one_or_none()
        if stat is None:
            stat = NationStat(server_id=self.server_id, nation_id=nation_id)
            self.session.add(stat)
            self.session.flush()
        return stat

    def _as_money(self, value: Decimal | float | int | str | None) -> Decimal:
        if value is None:
            return Decimal("0.00")
        return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    def build_overview(self, nation: Nation, role: str) -> NationResearchOverview:
        levels = self._levels_for_nation(nation.id)
        stat = self._get_or_create_stat(nation.id)
        treasury = self._as_money(stat.treasury_balance)

        nodes: list[ResearchNodeState] = []
        for node in CATALOG:
            level = levels.get(node.key, 0)
            maxed = level >= node.max_level

            locked = False
            lock_reason: str | None = None
            if node.requires:
                req_level = levels.get(node.requires, 0)
                if req_level < node.requires_level:
                    locked = True
                    req_node = get_node(node.requires)
                    req_title = req_node.title if req_node else node.requires
                    lock_reason = f"Требуется «{req_title}» ур. {node.requires_level}."

            next_cost = None if maxed else float(node.cost_for_level(level + 1))
            next_effect = None if maxed else node.effect_at(level + 1)
            can_afford = (
                not maxed and not locked and next_cost is not None and treasury >= self._as_money(next_cost)
            )

            nodes.append(
                ResearchNodeState(
                    key=node.key,
                    title=node.title,
                    description=node.description,
                    category=node.category,
                    icon=node.icon,
                    effect_key=node.effect_key,
                    effect_unit=node.effect_unit,
                    effect_per_level=node.effect_per_level,
                    level=level,
                    max_level=node.max_level,
                    current_effect=node.effect_at(level),
                    next_effect=next_effect,
                    next_cost=next_cost,
                    can_afford=can_afford,
                    locked=locked,
                    lock_reason=lock_reason,
                    requires=node.requires,
                    requires_level=node.requires_level,
                )
            )

        return NationResearchOverview(
            nation_slug=nation.slug,
            nation_title=nation.title,
            role=role,
            treasury_balance=float(treasury),
            nodes=nodes,
            effects=resolve_effects(levels),
        )

    def resolve_effects_for_server(self) -> list[NationResearchEffects]:
        rows = self.session.execute(
            select(Nation.slug, NationResearch.research_key, NationResearch.level)
            .join(NationResearch, NationResearch.nation_id == Nation.id)
            .where(NationResearch.server_id == self.server_id)
        ).all()
        by_slug: dict[str, dict[str, int]] = {}
        for slug, key, level in rows:
            by_slug.setdefault(slug, {})[key] = level
        return [
            NationResearchEffects(nation_slug=slug, effects=resolve_effects(levels))
            for slug, levels in by_slug.items()
        ]

    def apply_weekly_interest(self) -> dict:
        """Credit "Центробанк" interest to treasuries, at most once per period.

        Idempotent by period: a nation is skipped if it already received an
        ``interest`` transaction within :data:`INTEREST_PERIOD_DAYS`. Safe to call
        on a short timer — only nations that are due actually get paid.
        """
        rows = self.session.execute(
            select(Nation.id, NationResearch.research_key, NationResearch.level)
            .join(NationResearch, NationResearch.nation_id == Nation.id)
            .where(NationResearch.server_id == self.server_id)
        ).all()
        levels_by_nation: dict[UUID, dict[str, int]] = {}
        for nation_id, key, level in rows:
            levels_by_nation.setdefault(nation_id, {})[key] = level

        cutoff = datetime.now(timezone.utc) - timedelta(days=INTEREST_PERIOD_DAYS)
        applied: list[dict] = []
        total = Decimal("0.00")

        for nation_id, levels in levels_by_nation.items():
            percent = resolve_effects(levels).get("treasury_interest_percent", 0.0)
            if percent <= 0:
                continue

            last_at = self.session.execute(
                select(NationTreasuryTransaction.created_at)
                .where(
                    NationTreasuryTransaction.nation_id == nation_id,
                    NationTreasuryTransaction.server_id == self.server_id,
                    NationTreasuryTransaction.transaction_type == "interest",
                )
                .order_by(NationTreasuryTransaction.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if last_at is not None and last_at > cutoff:
                continue

            stat = self._get_or_create_stat(nation_id, lock=True)
            balance = self._as_money(stat.treasury_balance)
            if balance <= 0:
                continue
            interest = self._as_money(balance * Decimal(str(percent)) / Decimal("100"))
            if interest < Decimal("0.01"):
                continue

            stat.treasury_balance = self._as_money(balance + interest)
            self.session.add(
                NationTreasuryTransaction(
                    server_id=self.server_id,
                    transaction_type="interest",
                    nation_id=nation_id,
                    created_by_user_id=None,
                    gross_amount=interest,
                    fee_amount=Decimal("0.00"),
                    net_amount=interest,
                    comment=f"Проценты Центробанка ({percent:.1f}%)",
                    metadata_json={"percent": percent, "balance_before": str(balance)},
                )
            )
            self.activity.record(
                nation_id=nation_id,
                event_type="nation_treasury_interest",
                message=f"Центробанк начислил проценты: +{interest}.",
                metadata={"interest": str(interest), "percent": percent},
            )
            applied.append({"nation_id": str(nation_id), "interest": float(interest)})
            total += interest

        self.session.commit()
        return {"paid_nations": len(applied), "total_paid": float(total), "applied": applied}

    # ── writes ───────────────────────────────────────────────────────────────

    def purchase(
        self,
        *,
        nation: Nation,
        actor_user_id: UUID,
        actor_role: str,
        research_key: str,
    ) -> ResearchPurchaseResponse:
        if actor_role not in MANAGE_ROLES:
            raise NationResearchPermissionError(
                "Только глава или офицер государства может вкладываться в исследования."
            )

        node = get_node(research_key)
        if node is None:
            raise NationResearchError("Исследование не найдено.")

        levels = self._levels_for_nation(nation.id)
        current = levels.get(node.key, 0)
        if current >= node.max_level:
            raise NationResearchError("Достигнут максимальный уровень исследования.")

        if node.requires:
            req_level = levels.get(node.requires, 0)
            if req_level < node.requires_level:
                req_node = get_node(node.requires)
                req_title = req_node.title if req_node else node.requires
                raise NationResearchError(
                    f"Сначала изучите «{req_title}» до уровня {node.requires_level}."
                )

        target_level = current + 1
        cost = node.cost_for_level(target_level)

        stat = self._get_or_create_stat(nation.id, lock=True)
        balance = self._as_money(stat.treasury_balance)
        if balance < cost:
            raise NationResearchError("Недостаточно средств в казне государства.")

        stat.treasury_balance = self._as_money(balance - cost)

        row = self.session.execute(
            select(NationResearch).where(
                NationResearch.nation_id == nation.id,
                NationResearch.server_id == self.server_id,
                NationResearch.research_key == node.key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = NationResearch(
                server_id=self.server_id,
                nation_id=nation.id,
                research_key=node.key,
                level=target_level,
            )
            self.session.add(row)
        else:
            row.level = target_level

        self.session.add(
            NationTreasuryTransaction(
                server_id=self.server_id,
                transaction_type="research",
                nation_id=nation.id,
                created_by_user_id=actor_user_id,
                gross_amount=cost,
                fee_amount=Decimal("0.00"),
                net_amount=cost,
                comment=f"Исследование: {node.title} ур. {target_level}",
                metadata_json={
                    "nation_slug": nation.slug,
                    "research_key": node.key,
                    "new_level": target_level,
                },
            )
        )

        self.activity.record(
            nation_id=nation.id,
            event_type="nation_research_purchase",
            actor_user_id=actor_user_id,
            message=f"Государство изучило «{node.title}» до уровня {target_level}.",
            metadata={
                "research_key": node.key,
                "new_level": target_level,
                "cost": str(cost),
                "nation_slug": nation.slug,
            },
        )

        self.session.commit()
        self.session.refresh(stat)

        levels[node.key] = target_level
        return ResearchPurchaseResponse(
            message=f"Исследование «{node.title}» повышено до уровня {target_level}.",
            research_key=node.key,
            new_level=target_level,
            spent=float(cost),
            treasury_balance=float(self._as_money(stat.treasury_balance)),
            effects=resolve_effects(levels),
        )
