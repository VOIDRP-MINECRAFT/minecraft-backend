"""Static catalog of nation research nodes (the "tech tree").

A nation spends its treasury to level up research nodes; each level grants a
passive perk to every citizen. Effects are exposed as a machine-readable
``effect_key -> value`` map that the game plugins and other backend services
consume (market fee discount, capital Haste, gather bonus, ...).

The catalog is intentionally code-defined (not an admin CRUD) so balancing is a
reviewed deploy. Keep the ``effect_key`` values in sync with the consumers:

- ``market_fee_discount_percent`` — :mod:`player_market_service` fee calc
- ``capital_haste_level``         — gamesync plugin (potion effect near capital)
- ``gather_bonus_percent``        — gamesync plugin (extra ore/wood drops)
- ``bp_xp_bonus_percent``         — battlepass plugin
- ``extra_daily_quest_slots``     — daily quests plugin
- ``treasury_interest_percent``   — weekly treasury interest task (Phase 2)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

MONEY_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class ResearchNode:
    key: str
    title: str            # RU display title
    description: str      # RU description
    category: str         # RU category label ("Экономика" / "Развитие" / "Технологии")
    icon: str             # emoji for the WebGUI/site tile
    max_level: int
    base_cost: Decimal    # cost of the first level
    cost_growth: Decimal  # multiplier applied per already-owned level
    effect_key: str       # machine key consumed by plugins/services
    effect_per_level: float
    effect_unit: str      # "percent" | "level" | "count" — display hint
    requires: str | None = None       # prerequisite research key
    requires_level: int = 0           # required level of the prerequisite

    def cost_for_level(self, target_level: int) -> Decimal:
        """Cost to advance from ``target_level - 1`` to ``target_level`` (1-based)."""
        raw = self.base_cost * (self.cost_growth ** (target_level - 1))
        return raw.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    def effect_at(self, level: int) -> float:
        return round(self.effect_per_level * max(0, min(level, self.max_level)), 4)


# Order matters: this is the display order in the tech tree.
CATALOG: tuple[ResearchNode, ...] = (
    ResearchNode(
        key="market_guilds",
        title="Торговые гильдии",
        description="Снижает торговую комиссию рынка для граждан государства.",
        category="Экономика",
        icon="🏛️",
        max_level=5,
        base_cost=Decimal("50000"),
        cost_growth=Decimal("1.6"),
        effect_key="market_fee_discount_percent",
        effect_per_level=0.2,
        effect_unit="percent",
    ),
    ResearchNode(
        key="capital_workshops",
        title="Мастерские столицы",
        description="Даёт эффект Спешки гражданам в радиусе столицы.",
        category="Развитие",
        icon="⚒️",
        max_level=3,
        base_cost=Decimal("75000"),
        cost_growth=Decimal("1.8"),
        effect_key="capital_haste_level",
        effect_per_level=1,
        effect_unit="level",
    ),
    ResearchNode(
        key="labor_exchange",
        title="Биржа труда",
        description="Дополнительный слот ежедневных заданий для граждан.",
        category="Развитие",
        icon="📋",
        max_level=1,
        base_cost=Decimal("120000"),
        cost_growth=Decimal("1.0"),
        effect_key="extra_daily_quest_slots",
        effect_per_level=1,
        effect_unit="count",
    ),
    ResearchNode(
        key="academy",
        title="Академия наук",
        description="Ускоряет получение опыта Battle Pass гражданами.",
        category="Развитие",
        icon="🎓",
        max_level=4,
        base_cost=Decimal("60000"),
        cost_growth=Decimal("1.7"),
        effect_key="bp_xp_bonus_percent",
        effect_per_level=5,
        effect_unit="percent",
    ),
    ResearchNode(
        key="gathering_industry",
        title="Лесопилки и шахты",
        description="Шанс дополнительной добычи руд и древесины на территории.",
        category="Технологии",
        icon="⛏️",
        max_level=5,
        base_cost=Decimal("50000"),
        cost_growth=Decimal("1.6"),
        effect_key="gather_bonus_percent",
        effect_per_level=3,
        effect_unit="percent",
    ),
    ResearchNode(
        key="central_bank",
        title="Центробанк",
        description="Еженедельные проценты, начисляемые в казну государства.",
        category="Экономика",
        icon="🏦",
        max_level=4,
        base_cost=Decimal("100000"),
        cost_growth=Decimal("1.9"),
        effect_key="treasury_interest_percent",
        effect_per_level=0.5,
        effect_unit="percent",
        requires="market_guilds",
        requires_level=2,
    ),
)

CATALOG_BY_KEY: dict[str, ResearchNode] = {node.key: node for node in CATALOG}


def get_node(key: str) -> ResearchNode | None:
    return CATALOG_BY_KEY.get(key)


def resolve_effects(levels: dict[str, int]) -> dict[str, float]:
    """Aggregate ``effect_key -> value`` for a nation given its owned levels."""
    effects: dict[str, float] = {}
    for node in CATALOG:
        level = levels.get(node.key, 0)
        if level <= 0:
            continue
        effects[node.effect_key] = round(
            effects.get(node.effect_key, 0.0) + node.effect_at(level), 4
        )
    return effects
