"""Travelling trader (скупщик) — schedule, rolls, sessions and trades.

A visit happens every ``interval_minutes`` (Moscow time) and lasts ``duration_minutes``; with a
small chance it is an elite visit instead (short, only rare items). Stock is rolled once when the
visit is created: every slot rolls a rarity, then a quantity, then an item, so all players see the
same shared stock. The buy side (money paid to players) is scaled down to fit the payout budget.

The trade page opens only from the NPC: the plugin reports the right-click and the backend issues a
short session. A trade reserves stock under a row lock and queues a web action; the plugin checks
that the player still stands next to the trader, moves items and money, and reports the result.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.models.battlepass import BattlePassProgress
from apps.api.app.models.battlepass_season import BattlePassSeason
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import PlayerMarketWebAction
from apps.api.app.models.trader import (
    TraderCatalogItem,
    TraderSession,
    TraderSettings,
    TraderStock,
    TraderTransaction,
    TraderVisit,
)
from apps.api.app.services.notification_service import NotificationService

PHASES = ("early", "mid", "end")
SIDES = ("buy", "sell")
PENDING_TTL = timedelta(seconds=120)
ANCHOR = datetime(2026, 1, 5)   # a Monday; slots are counted from here in the configured timezone


class TraderError(Exception):
    """User-facing refusal (Russian text)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class SpawnPoint(BaseModel):
    world: str = "world"
    x: float = 0.5
    y: float = 64.0
    z: float = 0.5
    yaw: float = 0.0


class TraderConfig(BaseModel):
    """All tunables of one server. Stored as JSON; missing keys fall back to these defaults."""

    enabled: bool = False
    spawn: SpawnPoint = Field(default_factory=SpawnPoint)
    interact_radius: float = Field(default=8.0, ge=2, le=32)

    timezone: str = "Europe/Moscow"
    interval_minutes: int = Field(default=120, ge=10, le=24 * 60)
    duration_minutes: int = Field(default=30, ge=1, le=24 * 60)
    offset_minutes: int = Field(default=0, ge=0, le=24 * 60)
    announce_before_minutes: int = Field(default=10, ge=0, le=120)
    session_minutes: int = Field(default=15, ge=1, le=120)

    slots_buy: int = Field(default=27, ge=0, le=54)
    slots_sell: int = Field(default=27, ge=0, le=54)
    player_share_pct: float = Field(default=30.0, gt=0, le=100)

    # Rarity weights [*, **, ***] in percent and caps per visit for ** and ***.
    weights_normal: list[float] = Field(default_factory=lambda: [80.0, 19.0, 1.0])
    weights_weekend: list[float] = Field(default_factory=lambda: [65.0, 31.0, 4.0])
    cap_rarity2: int = Field(default=10, ge=0, le=54)
    cap_rarity3: int = Field(default=5, ge=0, le=54)
    # Quantity ranges per rarity (items), overridable per catalog item.
    qty_rarity1: list[int] = Field(default_factory=lambda: [64, 640])
    qty_rarity2: list[int] = Field(default_factory=lambda: [32, 128])
    qty_rarity3: list[int] = Field(default_factory=lambda: [1, 10])
    weekend_qty_mult: float = Field(default=1.5, ge=1, le=10)

    elite_chance_pct: float = Field(default=2.0, ge=0, le=100)
    elite_duration_minutes: int = Field(default=5, ge=1, le=120)
    elite_slots: int = Field(default=9, ge=1, le=54)
    elite_weights: list[float] = Field(default_factory=lambda: [0.0, 85.0, 15.0])

    # Prices: trader pays players unit_value × buy_price_mult, sells for unit_value × sell_price_mult.
    buy_price_mult: float = Field(default=1.0, gt=0, le=100)
    sell_price_mult: float = Field(default=1.5, gt=0, le=100)
    # Most money one visit may pay out (sum of the buy side at full stock).
    payout_budget: float = Field(default=20000.0, ge=0)
    weekend_budget_mult: float = Field(default=1.5, ge=1, le=10)
    elite_budget_mult: float = Field(default=1.5, ge=1, le=10)

    # Phase unlocks by the average battle pass level of active players.
    mid_avg_bp_level: float = Field(default=40.0, ge=0)
    end_avg_bp_level: float = Field(default=120.0, ge=0)
    active_days: int = Field(default=7, ge=1, le=60)
    min_active_players: int = Field(default=3, ge=1, le=1000)

    @field_validator("weights_normal", "weights_weekend", "elite_weights")
    @classmethod
    def _three_weights(cls, v: list[float]) -> list[float]:
        if len(v) != 3 or any(w < 0 for w in v) or sum(v) <= 0:
            raise ValueError("Нужно три неотрицательных веса редкостей с ненулевой суммой")
        return v

    @field_validator("qty_rarity1", "qty_rarity2", "qty_rarity3")
    @classmethod
    def _range(cls, v: list[int]) -> list[int]:
        if len(v) != 2 or v[0] < 1 or v[1] < v[0]:
            raise ValueError("Диапазон количества: два числа, от ≥1 и до ≥ от")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)
        return v


@dataclass
class RolledSlot:
    side: str
    slot: int
    item: TraderCatalogItem
    rarity: int
    qty: int
    unit_price: float


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class TraderService:
    def __init__(self, session: Session, server_id: UUID):
        self.session = session
        self.server_id = server_id

    # ── settings ────────────────────────────────────────────────────────────
    def settings_row(self) -> TraderSettings:
        row = self.session.scalar(select(TraderSettings).where(TraderSettings.server_id == self.server_id))
        if row is None:
            row = TraderSettings(server_id=self.server_id, config={})
            self.session.add(row)
            try:
                with self.session.begin_nested():
                    self.session.flush()
            except IntegrityError:
                row = self.session.scalar(select(TraderSettings).where(TraderSettings.server_id == self.server_id))
        return row

    def config(self) -> TraderConfig:
        return TraderConfig.model_validate(self.settings_row().config or {})

    def save_config(self, cfg: TraderConfig, updated_by: str | None) -> TraderSettings:
        row = self.settings_row()
        row.config = cfg.model_dump()
        row.updated_by = updated_by
        self.session.flush()
        return row

    # ── schedule ────────────────────────────────────────────────────────────
    def _slot_start(self, cfg: TraderConfig, at: datetime) -> datetime:
        tz = ZoneInfo(cfg.timezone)
        anchor = ANCHOR.replace(tzinfo=tz) + timedelta(minutes=cfg.offset_minutes)
        local = at.astimezone(tz)
        k = math.floor((local - anchor).total_seconds() / 60 / cfg.interval_minutes)
        return (anchor + timedelta(minutes=k * cfg.interval_minutes)).astimezone(timezone.utc)

    def _is_weekend(self, cfg: TraderConfig, start: datetime) -> bool:
        return start.astimezone(ZoneInfo(cfg.timezone)).weekday() >= 5

    def active_visit(self, now: datetime | None = None, create: bool = True) -> TraderVisit | None:
        now = now or _utcnow()
        visit = self.session.scalar(
            select(TraderVisit)
            .where(TraderVisit.server_id == self.server_id, TraderVisit.starts_at <= now, TraderVisit.ends_at > now)
            .order_by(TraderVisit.starts_at.desc())
            .limit(1)
        )
        if visit is not None or not create:
            return visit
        cfg = self.config()
        if not cfg.enabled:
            return None
        start = self._slot_start(cfg, now)
        if now >= start + timedelta(minutes=cfg.duration_minutes):
            return None
        existing = self._visit_at(start)
        if existing is not None:
            return existing if _as_utc(existing.ends_at) > now else None   # elite already left / ended by admin
        visit = self._create_visit(cfg, start, source="schedule")
        return visit if visit and _as_utc(visit.ends_at) > now else None

    def next_visit_start(self, now: datetime | None = None) -> datetime | None:
        now = now or _utcnow()
        cfg = self.config()
        if not cfg.enabled:
            return None
        start = self._slot_start(cfg, now)
        return start if start > now else start + timedelta(minutes=cfg.interval_minutes)

    def upcoming_visit(self, now: datetime | None = None) -> TraderVisit | None:
        """The next scheduled visit, rolled once we are inside the announcement window."""
        now = now or _utcnow()
        cfg = self.config()
        nxt = self.next_visit_start(now)
        if nxt is None or cfg.announce_before_minutes <= 0:
            return None
        if now < nxt - timedelta(minutes=cfg.announce_before_minutes):
            return None
        return self._visit_at(nxt) or self._create_visit(cfg, nxt, source="schedule")

    def _visit_at(self, start: datetime) -> TraderVisit | None:
        return self.session.scalar(
            select(TraderVisit).where(TraderVisit.server_id == self.server_id, TraderVisit.starts_at == start)
        )

    def _create_visit(
        self, cfg: TraderConfig, start: datetime, *, source: str, kind: str | None = None, created_by: str | None = None
    ) -> TraderVisit | None:
        seed = random.SystemRandom().getrandbits(62)
        rng = random.Random(seed)
        if kind is None:
            if rng.random() * 100 < cfg.elite_chance_pct:
                kind = "elite"
            elif self._is_weekend(cfg, start):
                kind = "weekend"
            else:
                kind = "normal"
        minutes = cfg.elite_duration_minutes if kind == "elite" else cfg.duration_minutes
        phases = self.current_phases(cfg)
        budget = cfg.payout_budget * (
            cfg.elite_budget_mult if kind == "elite" else cfg.weekend_budget_mult if kind == "weekend" else 1.0
        )
        visit = TraderVisit(
            server_id=self.server_id,
            kind=kind,
            starts_at=start,
            ends_at=start + timedelta(minutes=minutes),
            seed=seed,
            phases=",".join(phases),
            payout_budget=round(budget, 2),
            source=source,
            created_by=created_by,
        )
        try:
            with self.session.begin_nested():
                self.session.add(visit)
                self.session.flush()
                for rolled in self.roll(cfg, kind, phases, seed, budget):
                    self.session.add(TraderStock(
                        server_id=self.server_id,
                        visit_id=visit.id,
                        side=rolled.side,
                        slot=rolled.slot,
                        catalog_item_id=rolled.item.id,
                        item_key=rolled.item.item_key,
                        display_name=rolled.item.display_name,
                        rarity=rolled.rarity,
                        unit_price=rolled.unit_price,
                        qty_total=rolled.qty,
                        qty_left=rolled.qty,
                    ))
                self.session.flush()
        except IntegrityError:
            return self._visit_at(start)   # created concurrently by another request
        return visit

    def force_visit(self, kind: str, created_by: str | None) -> TraderVisit:
        if kind not in ("normal", "weekend", "elite"):
            raise TraderError("Неизвестный тип визита", 422)
        now = _utcnow()
        current = self.active_visit(now, create=False)
        if current is not None:
            raise TraderError("Скупщик уже на спавне — сначала завершите текущий визит")
        cfg = self.config()
        visit = self._create_visit(cfg, now.replace(microsecond=0), source="admin", kind=kind, created_by=created_by)
        if visit is None:
            raise TraderError("Не удалось создать визит, попробуйте ещё раз")
        return visit

    def end_visit(self, visit_id: UUID) -> TraderVisit:
        visit = self.session.get(TraderVisit, visit_id)
        if visit is None or visit.server_id != self.server_id:
            raise TraderError("Визит не найден", 404)
        now = _utcnow()
        if _as_utc(visit.starts_at) > now:
            visit.starts_at = now   # an upcoming visit ended in advance: make it an empty past visit
        if _as_utc(visit.ends_at) > now:
            visit.ends_at = now
        self.session.flush()
        return visit

    # ── phases ──────────────────────────────────────────────────────────────
    def bp_activity(self, cfg: TraderConfig) -> tuple[int, float]:
        season = self.session.scalar(
            select(BattlePassSeason.season_key).where(
                BattlePassSeason.server_id == self.server_id, BattlePassSeason.is_active.is_(True)
            )
        )
        since = _utcnow() - timedelta(days=cfg.active_days)
        q = select(func.count(BattlePassProgress.id), func.avg(BattlePassProgress.level)).where(
            BattlePassProgress.server_id == self.server_id,
            BattlePassProgress.updated_at >= since,
        )
        if season:
            q = q.where(BattlePassProgress.season == season)
        count, avg = self.session.execute(q).one()
        return int(count or 0), float(avg or 0.0)

    def current_phases(self, cfg: TraderConfig | None = None) -> list[str]:
        cfg = cfg or self.config()
        row = self.settings_row()
        count, avg = self.bp_activity(cfg)
        if count >= cfg.min_active_players:
            now = _utcnow()
            if row.mid_unlocked_at is None and avg >= cfg.mid_avg_bp_level:
                row.mid_unlocked_at = now
            if row.end_unlocked_at is None and avg >= cfg.end_avg_bp_level:
                row.end_unlocked_at = now
            self.session.flush()
        phases = ["early"]
        if row.mid_unlocked_at is not None:
            phases.append("mid")
        if row.end_unlocked_at is not None:
            phases.append("end")
        return phases

    # ── rolling ─────────────────────────────────────────────────────────────
    def roll(self, cfg: TraderConfig, kind: str, phases: list[str], seed: int, budget: float) -> list[RolledSlot]:
        catalog = self.session.scalars(
            select(TraderCatalogItem).where(
                TraderCatalogItem.server_id == self.server_id,
                TraderCatalogItem.enabled.is_(True),
                TraderCatalogItem.phase.in_(phases),
            ).order_by(TraderCatalogItem.item_key)
        ).all()
        rng = random.Random(seed)
        elite = kind == "elite"
        weights = cfg.elite_weights if elite else cfg.weights_weekend if kind == "weekend" else cfg.weights_normal
        caps = {1: 10**6, 2: cfg.cap_rarity2, 3: cfg.cap_rarity3}
        qty_mult = cfg.weekend_qty_mult if kind == "weekend" else 1.0
        used_keys: set[str] = set()
        rolled: list[RolledSlot] = []

        for side in SIDES:
            slots = cfg.elite_slots if elite else (cfg.slots_buy if side == "buy" else cfg.slots_sell)
            flag = "can_buy" if side == "buy" else "can_sell"
            pool = {r: [c for c in catalog if c.rarity == r and getattr(c, flag)] for r in (1, 2, 3)}
            counts = {1: 0, 2: 0, 3: 0}
            for slot in range(slots):
                rarity = rng.choices((1, 2, 3), weights=weights)[0]
                # Over the cap or nothing left of this rarity: step down, then up (elite never takes *).
                order = [rarity] + [r for r in (rarity - 1, rarity - 2) if r >= 1] + [r for r in (rarity + 1, rarity + 2) if r <= 3]
                if elite:
                    order = [r for r in order if weights[r - 1] > 0]
                chosen = None
                for r in order:
                    if counts[r] >= caps[r]:
                        continue
                    options = [c for c in pool[r] if c.item_key not in used_keys]
                    if options:
                        chosen = (r, rng.choice(options))
                        break
                if chosen is None:
                    break
                r, item = chosen
                lo, hi = (item.qty_min, item.qty_max) if item.qty_min and item.qty_max else getattr(cfg, f"qty_rarity{r}")
                qty = max(1, int(round(rng.randint(lo, max(lo, hi)) * qty_mult)))
                mult = cfg.buy_price_mult if side == "buy" else cfg.sell_price_mult
                price = round(max(0.01, item.unit_value * mult), 2)
                used_keys.add(item.item_key)
                counts[r] += 1
                rolled.append(RolledSlot(side=side, slot=slot, item=item, rarity=r, qty=qty, unit_price=price))

        buy = [s for s in rolled if s.side == "buy"]
        total = sum(s.qty * s.unit_price for s in buy)
        if budget > 0 and total > budget:
            factor = budget / total
            for s in buy:
                s.qty = max(1, int(s.qty * factor))
        return rolled

    # ── sessions (opened by right-clicking the NPC) ─────────────────────────
    def open_session(self, player_name: str) -> TraderSession:
        visit = self.active_visit()
        if visit is None:
            raise TraderError("Скупщика сейчас нет на спавне", 404)
        cfg = self.config()
        now = _utcnow()
        expires = min(_as_utc(visit.ends_at), now + timedelta(minutes=cfg.session_minutes))
        row = TraderSession(
            server_id=self.server_id, visit_id=visit.id, player_name=player_name.strip().lower()[:16], expires_at=expires
        )
        self.session.add(row)
        self.session.flush()
        return row

    def has_session(self, player_name: str, visit: TraderVisit) -> bool:
        return self.session.scalar(
            select(func.count(TraderSession.id)).where(
                TraderSession.server_id == self.server_id,
                TraderSession.visit_id == visit.id,
                TraderSession.player_name == player_name.strip().lower(),
                TraderSession.expires_at > _utcnow(),
            )
        ) > 0

    # ── stock view ──────────────────────────────────────────────────────────
    def player_cap(self, cfg: TraderConfig, stock: TraderStock) -> int:
        return max(1, math.ceil(stock.qty_total * cfg.player_share_pct / 100))

    def player_used(self, stock_ids: list[UUID], player_name: str) -> dict[UUID, int]:
        """Items a player has traded (done) or reserved (pending) per stock slot."""
        if not stock_ids:
            return {}
        used = case(
            (TraderTransaction.status == "done", TraderTransaction.qty_done),
            else_=TraderTransaction.qty_requested,
        )
        rows = self.session.execute(
            select(TraderTransaction.stock_id, func.sum(used))
            .where(
                TraderTransaction.stock_id.in_(stock_ids),
                func.lower(TraderTransaction.player_name) == player_name.strip().lower(),
                TraderTransaction.status.in_(("pending", "done")),
            )
            .group_by(TraderTransaction.stock_id)
        ).all()
        return {sid: int(total or 0) for sid, total in rows}

    def stock(self, visit: TraderVisit) -> list[TraderStock]:
        return list(
            self.session.scalars(
                select(TraderStock).where(TraderStock.visit_id == visit.id).order_by(TraderStock.side, TraderStock.slot)
            ).all()
        )

    # ── trades ──────────────────────────────────────────────────────────────
    def expire_stale(self, visit_id: UUID | None = None) -> int:
        cutoff = _utcnow() - PENDING_TTL
        q = select(TraderTransaction).where(
            TraderTransaction.server_id == self.server_id,
            TraderTransaction.status == "pending",
            TraderTransaction.created_at < cutoff,
        )
        if visit_id is not None:
            q = q.where(TraderTransaction.visit_id == visit_id)
        stale = self.session.scalars(q.with_for_update(skip_locked=True)).all()
        for tx in stale:
            tx.status = "expired"
            tx.error = "Игровой сервер не обработал сделку вовремя"
            tx.completed_at = _utcnow()
            self.session.execute(
                update(TraderStock).where(TraderStock.id == tx.stock_id).values(qty_left=TraderStock.qty_left + tx.qty_requested)
            )
            if tx.web_action_id:
                self.session.execute(
                    update(PlayerMarketWebAction)
                    .where(PlayerMarketWebAction.id == tx.web_action_id, PlayerMarketWebAction.status == "pending")
                    .values(status="failed", error_message="expired", processed_at=_utcnow())
                )
        if stale:
            self.session.flush()
        return len(stale)

    def request_trade(self, player: PlayerAccount, stock_id: UUID, qty: int) -> TraderTransaction:
        if qty < 1 or qty > 6400:
            raise TraderError("Количество должно быть от 1 до 6400", 422)
        visit = self.active_visit(create=False)
        if visit is None:
            raise TraderError("Скупщик уже ушёл", 404)
        name = player.minecraft_nickname
        if not self.has_session(name, visit):
            raise TraderError("Подойдите к скупщику на спавне и нажмите на него правой кнопкой", 403)
        self.expire_stale(visit.id)
        pending = self.session.scalar(
            select(func.count(TraderTransaction.id)).where(
                TraderTransaction.visit_id == visit.id,
                func.lower(TraderTransaction.player_name) == name.lower(),
                TraderTransaction.status == "pending",
            )
        )
        if pending:
            raise TraderError("Дождитесь завершения предыдущей сделки")

        stock = self.session.scalar(select(TraderStock).where(TraderStock.id == stock_id).with_for_update())
        if stock is None or stock.visit_id != visit.id:
            raise TraderError("Этого предмета нет у скупщика", 404)
        cfg = self.config()
        cap = self.player_cap(cfg, stock)
        used = self.player_used([stock.id], name).get(stock.id, 0)
        allowed = min(qty, stock.qty_left, cap - used)
        if stock.qty_left <= 0:
            raise TraderError("Этот лот уже разобрали")
        if allowed <= 0:
            raise TraderError(f"Ваш лимит по этому лоту исчерпан: не больше {cap} шт. на игрока")

        stock.qty_left -= allowed
        tx = TraderTransaction(
            server_id=self.server_id,
            visit_id=visit.id,
            stock_id=stock.id,
            user_id=player.user_id,
            player_name=name,
            side=stock.side,
            item_key=stock.item_key,
            qty_requested=allowed,
            unit_price=stock.unit_price,
            status="pending",
        )
        self.session.add(tx)
        self.session.flush()
        action = PlayerMarketWebAction(
            server_id=self.server_id,
            player_name=name,
            action_type="trader_trade",
            payload_json={
                "tx_id": str(tx.id),
                "side": stock.side,
                "item_key": stock.item_key,
                "display": stock.display_name,
                "amount": allowed,
                "unit_price": stock.unit_price,
            },
            status="pending",
        )
        self.session.add(action)
        self.session.flush()
        tx.web_action_id = action.id
        self.session.flush()
        return tx

    def complete_trade(self, tx_id: UUID, ok: bool, qty_done: int, error: str | None) -> TraderTransaction:
        tx = self.session.scalar(select(TraderTransaction).where(TraderTransaction.id == tx_id).with_for_update())
        if tx is None or tx.server_id != self.server_id:
            raise TraderError("Сделка не найдена", 404)
        if tx.status in ("done", "failed"):
            return tx   # already settled (retry from the plugin)
        done = max(0, min(int(qty_done if ok else 0), tx.qty_requested))
        stock = self.session.scalar(select(TraderStock).where(TraderStock.id == tx.stock_id).with_for_update())
        if tx.status == "expired":
            # The reservation was already returned; take back what the plugin actually moved.
            stock.qty_left = max(0, stock.qty_left - done)
        else:
            stock.qty_left += tx.qty_requested - done
        tx.qty_done = done
        tx.total = round(done * tx.unit_price, 2)
        tx.status = "done" if done > 0 else "failed"
        tx.error = (error or None) if done < tx.qty_requested else None
        tx.completed_at = _utcnow()
        if tx.web_action_id:
            self.session.execute(
                update(PlayerMarketWebAction)
                .where(PlayerMarketWebAction.id == tx.web_action_id)
                .values(status="done" if done > 0 else "failed", error_message=(error or "")[:500] or None, processed_at=_utcnow())
            )
        self.session.flush()
        return tx

    # ── announcements (WebGUI notifications for online players) ─────────────
    def announce(self, online: list[str]) -> None:
        names = sorted({n.strip().lower() for n in online if n and n.strip()})[:200]
        now = _utcnow()
        cfg = self.config()
        visit = self.active_visit(now)
        messages: list[tuple[str, str, str]] = []
        if visit is not None and visit.announced_arrival_at is None:
            visit.announced_arrival_at = now
            minutes = max(1, round((_as_utc(visit.ends_at) - now).total_seconds() / 60))
            if visit.kind == "elite":
                messages.append(("Элитный скупщик на спавне", f"Только редкие предметы и всего {minutes} мин. Правый клик по нему открывает торговлю.", "violet"))
            elif visit.kind == "weekend":
                messages.append(("Скупщик выходного дня на спавне", f"Больше редких предметов и крупнее лоты. Уйдёт через {minutes} мин.", "gold"))
            else:
                messages.append(("Скупщик пришёл на спавн", f"Лоты общие на всех — кто первый. Уйдёт через {minutes} мин.", "gold"))
        upcoming = self.upcoming_visit(now) if visit is None else None
        if upcoming is not None and upcoming.announced_soon_at is None and _as_utc(upcoming.starts_at) > now:
            upcoming.announced_soon_at = now
            minutes = max(1, round((_as_utc(upcoming.starts_at) - now).total_seconds() / 60))
            messages.append(("Скоро придёт скупщик", f"Через {minutes} мин. он будет на спавне. Приготовьте ресурсы на продажу.", "gold"))
        if not messages or not names:
            self.session.flush()
            return
        accounts = self.session.execute(
            select(PlayerAccount.user_id).where(PlayerAccount.minecraft_nickname_normalized.in_(names))
        ).scalars().all()
        notifier = NotificationService(self.session, self.server_id)
        for user_id in accounts:
            for title, body, accent in messages:
                notifier.create(user_id=user_id, type="trader", title=title, body=body, icon="market", accent=accent)
        self.session.flush()
