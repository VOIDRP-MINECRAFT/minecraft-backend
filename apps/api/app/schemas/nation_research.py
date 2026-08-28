from __future__ import annotations

from pydantic import BaseModel


class ResearchNodeState(BaseModel):
    key: str
    title: str
    description: str
    category: str
    icon: str
    effect_key: str
    effect_unit: str
    effect_per_level: float
    level: int
    max_level: int
    current_effect: float
    next_effect: float | None       # None when already at max level
    next_cost: float | None         # None when already at max level
    can_afford: bool
    locked: bool                    # prerequisite not yet satisfied
    lock_reason: str | None
    requires: str | None
    requires_level: int


class NationResearchOverview(BaseModel):
    nation_slug: str
    nation_title: str
    role: str
    treasury_balance: float
    nodes: list[ResearchNodeState]
    effects: dict[str, float]


class ResearchPurchaseRequest(BaseModel):
    research_key: str


class ResearchPurchaseResponse(BaseModel):
    message: str
    research_key: str
    new_level: int
    spent: float
    treasury_balance: float
    effects: dict[str, float]


class NationResearchEffects(BaseModel):
    nation_slug: str
    effects: dict[str, float]


class NationResearchEffectsResponse(BaseModel):
    nations: list[NationResearchEffects]
