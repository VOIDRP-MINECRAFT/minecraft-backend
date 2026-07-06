from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.api.app.core.security import utc_now
from apps.api.app.models.economy_market import EconomyMarketItem
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import (
    PlayerMarketBuyOrder,
    PlayerMarketPendingDelivery,
    PlayerMarketSellOrder,
    PlayerMarketTrade,
)
from apps.api.app.models.user import User
from apps.api.app.schemas.player_market import (
    PlayerMarketBuyOrderCreate,
    PlayerMarketBuyOrderRead,
    PlayerMarketCancelBuyOrderResponse,
    PlayerMarketCancelSellOrderResponse,
    PlayerMarketCreateBuyOrderResponse,
    PlayerMarketCreateSellOrderResponse,
    PlayerMarketDeliveryAckRequest,
    PlayerMarketExpireResponse,
    PlayerMarketImmediateFill,
    PlayerMarketItemSummary,
    PlayerMarketItemSummaryListResponse,
    PlayerMarketOrderBookEntry,
    PlayerMarketOrderBookResponse,
    PlayerMarketPendingDeliveriesResponse,
    PlayerMarketPendingDeliveryRead,
    PlayerMarketSellOrderCreate,
    PlayerMarketSellOrderRead,
    PlayerMarketTradeListResponse,
    PlayerMarketTradeRead,
)

MONEY_QUANT = Decimal("0.01")
FEE_PERCENT = Decimal("2.00")
FEE_PERCENT_PREMIUM = Decimal("1.00")
CANCEL_FEE_PERCENT = Decimal("0.50")
ORDER_EXPIRY_DAYS = 7
MAX_ACTIVE_SELL_PER_PLAYER = 50
MAX_ACTIVE_BUY_PER_PLAYER = 50
MAX_VOLUME_PER_PLAYER_PER_ITEM = 10_000
ACTIVE_STATUSES = ("active", "partially_filled")


class PlayerMarketError(Exception):
    pass


class PlayerMarketNotFoundError(PlayerMarketError):
    pass


class PlayerMarketValidationError(PlayerMarketError):
    pass


class PlayerMarketConflictError(PlayerMarketError):
    pass


class PlayerMarketService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    # ── Create orders ──────────────────────────────────────────────────────────

    def create_sell_order(self, payload: PlayerMarketSellOrderCreate) -> PlayerMarketCreateSellOrderResponse:
        item_key = self._normalize_key(payload.item_key)
        unit_price = self._money(payload.unit_price)

        if unit_price <= 0:
            raise PlayerMarketValidationError("Цена должна быть больше нуля.")
        if payload.total_amount <= 0:
            raise PlayerMarketValidationError("Количество должно быть больше нуля.")

        active_count = self.session.scalar(
            select(func.count()).select_from(PlayerMarketSellOrder).where(
                PlayerMarketSellOrder.server_id == self.server_id,
                PlayerMarketSellOrder.seller_player_name == payload.seller_player_name,
                PlayerMarketSellOrder.status.in_(ACTIVE_STATUSES),
            )
        ) or 0
        if active_count >= MAX_ACTIVE_SELL_PER_PLAYER:
            raise PlayerMarketValidationError(
                f"Достигнут лимит активных ордеров на продажу ({MAX_ACTIVE_SELL_PER_PLAYER})."
            )

        existing_volume = self.session.scalar(
            select(func.sum(PlayerMarketSellOrder.remaining_amount)).where(
                PlayerMarketSellOrder.server_id == self.server_id,
                PlayerMarketSellOrder.seller_player_name.ilike(payload.seller_player_name),
                PlayerMarketSellOrder.item_key == item_key,
                PlayerMarketSellOrder.status.in_(ACTIVE_STATUSES),
            )
        ) or 0
        if existing_volume + payload.total_amount > MAX_VOLUME_PER_PLAYER_PER_ITEM:
            raise PlayerMarketValidationError(
                f"Превышен лимит объёма ордеров по одному товару ({MAX_VOLUME_PER_PLAYER_PER_ITEM} шт.)."
            )

        self._ensure_market_item(item_key, payload.display_name, float(unit_price))

        meta = dict(payload.metadata_json or {})
        if payload.is_premium:
            meta["is_premium"] = True

        order = PlayerMarketSellOrder(
            server_id=self.server_id,
            seller_player_name=payload.seller_player_name,
            item_key=item_key,
            display_name=payload.display_name,
            item_stack_base64=payload.item_stack_base64,
            total_amount=payload.total_amount,
            remaining_amount=payload.total_amount,
            filled_amount=0,
            unit_price=unit_price,
            status="active",
            expires_at=utc_now() + timedelta(days=ORDER_EXPIRY_DAYS),
            metadata_json=meta,
        )
        self.session.add(order)
        self.session.flush()

        fills = self._match_sell_against_buy_orders(order)
        self.session.commit()
        self.session.refresh(order)

        return PlayerMarketCreateSellOrderResponse(
            message="Ордер на продажу размещён.",
            order=PlayerMarketSellOrderRead.model_validate(order),
            immediate_fills=fills,
        )

    def create_buy_order(self, payload: PlayerMarketBuyOrderCreate) -> PlayerMarketCreateBuyOrderResponse:
        item_key = self._normalize_key(payload.item_key)
        unit_price = self._money(payload.unit_price)
        reserved = self._money(payload.reserved_funds)
        expected_reserve = self._money(unit_price * Decimal(payload.total_amount))

        if unit_price <= 0:
            raise PlayerMarketValidationError("Цена должна быть больше нуля.")
        if payload.total_amount <= 0:
            raise PlayerMarketValidationError("Количество должно быть больше нуля.")

        # Allow 1% tolerance for floating-point rounding
        tolerance = self._money(expected_reserve * Decimal("0.01"))
        if abs(reserved - expected_reserve) > tolerance:
            raise PlayerMarketValidationError(
                f"Зарезервированная сумма ({reserved}) не соответствует цене×количество ({expected_reserve})."
            )

        active_count = self.session.scalar(
            select(func.count()).select_from(PlayerMarketBuyOrder).where(
                PlayerMarketBuyOrder.server_id == self.server_id,
                PlayerMarketBuyOrder.buyer_player_name == payload.buyer_player_name,
                PlayerMarketBuyOrder.status.in_(ACTIVE_STATUSES),
            )
        ) or 0
        if active_count >= MAX_ACTIVE_BUY_PER_PLAYER:
            raise PlayerMarketValidationError(
                f"Достигнут лимит активных ордеров на покупку ({MAX_ACTIVE_BUY_PER_PLAYER})."
            )

        existing_volume = self.session.scalar(
            select(func.sum(PlayerMarketBuyOrder.remaining_amount)).where(
                PlayerMarketBuyOrder.server_id == self.server_id,
                PlayerMarketBuyOrder.buyer_player_name.ilike(payload.buyer_player_name),
                PlayerMarketBuyOrder.item_key == item_key,
                PlayerMarketBuyOrder.status.in_(ACTIVE_STATUSES),
            )
        ) or 0
        if existing_volume + payload.total_amount > MAX_VOLUME_PER_PLAYER_PER_ITEM:
            raise PlayerMarketValidationError(
                f"Превышен лимит объёма ордеров по одному товару ({MAX_VOLUME_PER_PLAYER_PER_ITEM} шт.)."
            )

        self._ensure_market_item(item_key, payload.display_name, float(unit_price))

        order = PlayerMarketBuyOrder(
            server_id=self.server_id,
            buyer_player_name=payload.buyer_player_name,
            item_key=item_key,
            display_name=payload.display_name,
            item_display_base64=getattr(payload, "item_display_base64", None),
            total_amount=payload.total_amount,
            remaining_amount=payload.total_amount,
            filled_amount=0,
            unit_price=unit_price,
            reserved_funds=reserved,
            status="active",
            expires_at=utc_now() + timedelta(days=ORDER_EXPIRY_DAYS),
            metadata_json=payload.metadata_json or {},
        )
        self.session.add(order)
        self.session.flush()

        fills = self._match_buy_against_sell_orders(order)
        self.session.commit()
        self.session.refresh(order)

        return PlayerMarketCreateBuyOrderResponse(
            message="Ордер на покупку размещён.",
            order=PlayerMarketBuyOrderRead.model_validate(order),
            immediate_fills=fills,
        )

    # ── Cancel orders ──────────────────────────────────────────────────────────

    def cancel_sell_order(self, order_id: UUID, requester: str) -> PlayerMarketCancelSellOrderResponse:
        order = self.session.execute(
            select(PlayerMarketSellOrder)
            .where(
                PlayerMarketSellOrder.id == order_id,
                PlayerMarketSellOrder.server_id == self.server_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if order is None:
            raise PlayerMarketNotFoundError("Ордер на продажу не найден.")
        if order.seller_player_name.lower() != requester.lower():
            raise PlayerMarketConflictError("Нет прав для отмены этого ордера.")
        if order.status not in ACTIVE_STATUSES:
            raise PlayerMarketConflictError("Ордер уже завершён или отменён.")

        returned_amount = order.remaining_amount
        gross_value = self._money(Decimal(returned_amount) * Decimal(str(order.unit_price)))
        cancel_fee = self._money(gross_value * CANCEL_FEE_PERCENT / Decimal("100"))

        order.status = "cancelled"
        order.cancelled_at = utc_now()
        order.remaining_amount = 0

        # Items are returned immediately by the plugin via the response fields
        # (returned_amount + item_stack_base64). No pending delivery created to
        # avoid double-delivery when the player is online.
        # Plugin deducts cancel_fee_coins from player balance after returning items.

        self.session.commit()
        self.session.refresh(order)

        return PlayerMarketCancelSellOrderResponse(
            message="Ордер на продажу отменён. Предметы возвращены.",
            order=PlayerMarketSellOrderRead.model_validate(order),
            returned_amount=returned_amount,
            cancel_fee_coins=float(cancel_fee),
            item_stack_base64=order.item_stack_base64,
        )

    def cancel_buy_order(self, order_id: UUID, requester: str) -> PlayerMarketCancelBuyOrderResponse:
        order = self.session.execute(
            select(PlayerMarketBuyOrder)
            .where(
                PlayerMarketBuyOrder.id == order_id,
                PlayerMarketBuyOrder.server_id == self.server_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if order is None:
            raise PlayerMarketNotFoundError("Ордер на покупку не найден.")
        if order.buyer_player_name.lower() != requester.lower():
            raise PlayerMarketConflictError("Нет прав для отмены этого ордера.")
        if order.status not in ACTIVE_STATUSES:
            raise PlayerMarketConflictError("Ордер уже завершён или отменён.")

        gross_funds = self._money(
            Decimal(str(order.unit_price)) * Decimal(order.remaining_amount)
        )
        cancel_fee = self._money(gross_funds * CANCEL_FEE_PERCENT / Decimal("100"))
        returned_funds = gross_funds - cancel_fee

        order.status = "cancelled"
        order.cancelled_at = utc_now()
        order.remaining_amount = 0
        order.reserved_funds = Decimal("0")

        # Funds are returned immediately by the plugin via the response field
        # (returned_funds, already net of cancel fee). No pending delivery created.

        self.session.commit()
        self.session.refresh(order)

        return PlayerMarketCancelBuyOrderResponse(
            message="Ордер на покупку отменён. Средства возвращены (за вычетом комиссии 0.5%).",
            order=PlayerMarketBuyOrderRead.model_validate(order),
            returned_funds=float(returned_funds),
        )

    # ── Order book / public reads ──────────────────────────────────────────────

    def get_order_book(self, item_key: str, exclude_player: str | None = None) -> PlayerMarketOrderBookResponse:
        item_key = self._normalize_key(item_key)

        params: dict = {"key": item_key, "sid": str(self.server_id)}
        player_filter_sell = ""
        player_filter_buy  = ""
        if exclude_player:
            params["excl"] = exclude_player.lower()
            player_filter_sell = " AND LOWER(seller_player_name) != :excl"
            player_filter_buy  = " AND LOWER(buyer_player_name) != :excl"

        sell_rows = self.session.execute(
            text(f"""
                SELECT unit_price, SUM(remaining_amount) AS total_amount, COUNT(*) AS order_count
                FROM player_market_sell_orders
                WHERE server_id = :sid AND item_key = :key AND status IN ('active', 'partially_filled') AND remaining_amount > 0{player_filter_sell}
                GROUP BY unit_price
                ORDER BY unit_price ASC
                LIMIT 20
            """),
            params,
        ).fetchall()

        buy_rows = self.session.execute(
            text(f"""
                SELECT unit_price, SUM(remaining_amount) AS total_amount, COUNT(*) AS order_count
                FROM player_market_buy_orders
                WHERE server_id = :sid AND item_key = :key AND status IN ('active', 'partially_filled') AND remaining_amount > 0{player_filter_buy}
                GROUP BY unit_price
                ORDER BY unit_price DESC
                LIMIT 20
            """),
            params,
        ).fetchall()

        last_trade = self.session.execute(
            select(PlayerMarketTrade)
            .where(
                PlayerMarketTrade.item_key == item_key,
                PlayerMarketTrade.server_id == self.server_id,
            )
            .order_by(PlayerMarketTrade.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        best_ask = float(sell_rows[0][0]) if sell_rows else None
        best_bid = float(buy_rows[0][0]) if buy_rows else None
        spread = round(best_ask - best_bid, 2) if best_ask and best_bid else None

        return PlayerMarketOrderBookResponse(
            item_key=item_key,
            sell_side=[
                PlayerMarketOrderBookEntry(
                    unit_price=float(r[0]),
                    total_amount=int(r[1]),
                    order_count=int(r[2]),
                )
                for r in sell_rows
            ],
            buy_side=[
                PlayerMarketOrderBookEntry(
                    unit_price=float(r[0]),
                    total_amount=int(r[1]),
                    order_count=int(r[2]),
                )
                for r in buy_rows
            ],
            last_trade_price=float(last_trade.unit_price) if last_trade else None,
            last_trade_at=last_trade.created_at if last_trade else None,
            spread=spread,
        )

    def list_items_summary(self) -> PlayerMarketItemSummaryListResponse:
        """Return aggregated per-item data for the market hub page."""
        rows = self.session.execute(
            text("""
                WITH sell_agg AS (
                    SELECT item_key,
                           MIN(display_name) AS display_name,
                           MIN(unit_price)   AS best_sell_price,
                           SUM(remaining_amount) AS active_sell_qty,
                           COUNT(*)          AS active_sell_orders
                    FROM player_market_sell_orders
                    WHERE server_id = :sid AND status IN ('active', 'partially_filled') AND remaining_amount > 0
                    GROUP BY item_key
                ),
                buy_agg AS (
                    SELECT item_key,
                           MAX(unit_price)   AS best_buy_price,
                           SUM(remaining_amount) AS active_buy_qty,
                           COUNT(*)          AS active_buy_orders
                    FROM player_market_buy_orders
                    WHERE server_id = :sid AND status IN ('active', 'partially_filled') AND remaining_amount > 0
                    GROUP BY item_key
                ),
                trade_agg AS (
                    SELECT item_key,
                           SUM(CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN amount ELSE 0 END) AS vol_24h,
                           MAX(unit_price) FILTER (WHERE created_at = (SELECT MAX(created_at) FROM player_market_trades t2 WHERE t2.item_key = player_market_trades.item_key AND t2.server_id = :sid)) AS last_price,
                           MAX(created_at) AS last_trade_at
                    FROM player_market_trades
                    WHERE server_id = :sid
                    GROUP BY item_key
                )
                SELECT
                    COALESCE(s.item_key, b.item_key, tr.item_key) AS item_key,
                    s.display_name                                AS display_name,
                    s.best_sell_price,
                    b.best_buy_price,
                    COALESCE(s.active_sell_orders, 0)             AS active_sell_orders,
                    COALESCE(b.active_buy_orders, 0)              AS active_buy_orders,
                    COALESCE(tr.vol_24h, 0)                       AS volume_24h,
                    tr.last_price                                 AS last_trade_price,
                    tr.last_trade_at
                FROM sell_agg s
                FULL OUTER JOIN buy_agg b ON s.item_key = b.item_key
                FULL OUTER JOIN trade_agg tr ON COALESCE(s.item_key, b.item_key) = tr.item_key
                ORDER BY COALESCE(tr.vol_24h, 0) DESC, item_key ASC
                LIMIT 500
            """),
            {"sid": str(self.server_id)},
        ).fetchall()

        items = [
            PlayerMarketItemSummary(
                item_key=r[0],
                display_name=r[1],
                best_sell_price=float(r[2]) if r[2] is not None else None,
                best_buy_price=float(r[3]) if r[3] is not None else None,
                active_sell_orders=int(r[4]),
                active_buy_orders=int(r[5]),
                volume_24h=int(r[6]),
                last_trade_price=float(r[7]) if r[7] is not None else None,
                last_trade_at=r[8],
            )
            for r in rows
        ]
        return PlayerMarketItemSummaryListResponse(total=len(items), items=items)

    def list_sell_orders(self, item_key: str | None = None, limit: int = 100) -> list[PlayerMarketSellOrder]:
        stmt = (
            select(PlayerMarketSellOrder)
            .where(PlayerMarketSellOrder.server_id == self.server_id)
            .where(PlayerMarketSellOrder.status.in_(ACTIVE_STATUSES))
            .where(PlayerMarketSellOrder.remaining_amount > 0)
        )
        if item_key:
            stmt = stmt.where(PlayerMarketSellOrder.item_key == self._normalize_key(item_key))
        stmt = stmt.order_by(PlayerMarketSellOrder.unit_price.asc(), PlayerMarketSellOrder.created_at.asc())
        stmt = stmt.limit(min(max(limit, 1), 500))
        return list(self.session.execute(stmt).scalars().all())

    def list_buy_orders(self, item_key: str | None = None, limit: int = 100) -> list[PlayerMarketBuyOrder]:
        stmt = (
            select(PlayerMarketBuyOrder)
            .where(PlayerMarketBuyOrder.server_id == self.server_id)
            .where(PlayerMarketBuyOrder.status.in_(ACTIVE_STATUSES))
            .where(PlayerMarketBuyOrder.remaining_amount > 0)
        )
        if item_key:
            stmt = stmt.where(PlayerMarketBuyOrder.item_key == self._normalize_key(item_key))
        stmt = stmt.order_by(PlayerMarketBuyOrder.unit_price.desc(), PlayerMarketBuyOrder.created_at.asc())
        stmt = stmt.limit(min(max(limit, 1), 500))
        return list(self.session.execute(stmt).scalars().all())

    def list_trades(self, item_key: str | None = None, limit: int = 50) -> PlayerMarketTradeListResponse:
        stmt = select(PlayerMarketTrade).where(PlayerMarketTrade.server_id == self.server_id)
        if item_key:
            stmt = stmt.where(PlayerMarketTrade.item_key == self._normalize_key(item_key))
        stmt = stmt.order_by(PlayerMarketTrade.created_at.desc()).limit(min(max(limit, 1), 500))
        trades = list(self.session.execute(stmt).scalars().all())
        return PlayerMarketTradeListResponse(
            total=len(trades),
            items=[PlayerMarketTradeRead.model_validate(t) for t in trades],
        )

    def list_my_sell_orders(
        self, player_name: str, include_inactive: bool = False, limit: int = 50
    ) -> list[PlayerMarketSellOrder]:
        stmt = select(PlayerMarketSellOrder).where(
            PlayerMarketSellOrder.server_id == self.server_id,
            PlayerMarketSellOrder.seller_player_name.ilike(player_name),
        )
        if not include_inactive:
            stmt = stmt.where(PlayerMarketSellOrder.status.in_(ACTIVE_STATUSES))
        stmt = stmt.order_by(PlayerMarketSellOrder.created_at.desc()).limit(min(limit, 200))
        return list(self.session.execute(stmt).scalars().all())

    def list_my_buy_orders(
        self, player_name: str, include_inactive: bool = False, limit: int = 50
    ) -> list[PlayerMarketBuyOrder]:
        stmt = select(PlayerMarketBuyOrder).where(
            PlayerMarketBuyOrder.server_id == self.server_id,
            PlayerMarketBuyOrder.buyer_player_name.ilike(player_name),
        )
        if not include_inactive:
            stmt = stmt.where(PlayerMarketBuyOrder.status.in_(ACTIVE_STATUSES))
        stmt = stmt.order_by(PlayerMarketBuyOrder.created_at.desc()).limit(min(limit, 200))
        return list(self.session.execute(stmt).scalars().all())

    def list_my_trades(self, player_name: str, limit: int = 50) -> PlayerMarketTradeListResponse:
        stmt = (
            select(PlayerMarketTrade)
            .where(PlayerMarketTrade.server_id == self.server_id)
            .where(
                (PlayerMarketTrade.seller_player_name.ilike(player_name))
                | (PlayerMarketTrade.buyer_player_name.ilike(player_name))
            )
            .order_by(PlayerMarketTrade.created_at.desc())
            .limit(min(limit, 200))
        )
        trades = list(self.session.execute(stmt).scalars().all())
        return PlayerMarketTradeListResponse(
            total=len(trades),
            items=[PlayerMarketTradeRead.model_validate(t) for t in trades],
        )

    # ── Pending deliveries ─────────────────────────────────────────────────────

    def get_pending_deliveries(self, player_name: str) -> PlayerMarketPendingDeliveriesResponse:
        rows = self.session.execute(
            select(PlayerMarketPendingDelivery).where(
                PlayerMarketPendingDelivery.server_id == self.server_id,
                PlayerMarketPendingDelivery.player_name.ilike(player_name),
                PlayerMarketPendingDelivery.delivered.is_(False),
            ).order_by(PlayerMarketPendingDelivery.created_at.asc()).limit(100)
        ).scalars().all()
        return PlayerMarketPendingDeliveriesResponse(
            total=len(rows),
            deliveries=[PlayerMarketPendingDeliveryRead.model_validate(r) for r in rows],
        )

    def ack_deliveries(self, player_name: str, req: PlayerMarketDeliveryAckRequest) -> int:
        if not req.delivery_ids:
            return 0
        rows = self.session.execute(
            select(PlayerMarketPendingDelivery).where(
                PlayerMarketPendingDelivery.server_id == self.server_id,
                PlayerMarketPendingDelivery.id.in_(req.delivery_ids),
                PlayerMarketPendingDelivery.player_name.ilike(player_name),
                PlayerMarketPendingDelivery.delivered.is_(False),
            )
        ).scalars().all()
        now = utc_now()
        for row in rows:
            row.delivered = True
            row.delivered_at = now
        self.session.commit()
        return len(rows)

    # ── Expiry ─────────────────────────────────────────────────────────────────

    def expire_orders(self) -> PlayerMarketExpireResponse:
        now = utc_now()

        expired_sells = self.session.execute(
            select(PlayerMarketSellOrder).where(
                PlayerMarketSellOrder.server_id == self.server_id,
                PlayerMarketSellOrder.expires_at <= now,
                PlayerMarketSellOrder.status.in_(ACTIVE_STATUSES),
            ).with_for_update(skip_locked=True)
        ).scalars().all()

        for order in expired_sells:
            if order.remaining_amount > 0:
                self.session.add(PlayerMarketPendingDelivery(
                    server_id=self.server_id,
                    player_name=order.seller_player_name,
                    delivery_type="expiry_refund",
                    sell_order_id=order.id,
                    amount_items=order.remaining_amount,
                    item_stack_base64=order.item_stack_base64,
                    item_key=order.item_key,
                    display_name=order.display_name,
                ))
            order.status = "expired"
            order.remaining_amount = 0

        expired_buys = self.session.execute(
            select(PlayerMarketBuyOrder).where(
                PlayerMarketBuyOrder.server_id == self.server_id,
                PlayerMarketBuyOrder.expires_at <= now,
                PlayerMarketBuyOrder.status.in_(ACTIVE_STATUSES),
            ).with_for_update(skip_locked=True)
        ).scalars().all()

        for order in expired_buys:
            refund = self._money(Decimal(str(order.unit_price)) * Decimal(order.remaining_amount))
            if refund > 0:
                self.session.add(PlayerMarketPendingDelivery(
                    server_id=self.server_id,
                    player_name=order.buyer_player_name,
                    delivery_type="expiry_refund",
                    buy_order_id=order.id,
                    amount_money=refund,
                ))
            order.status = "expired"
            order.remaining_amount = 0
            order.reserved_funds = Decimal("0")

        self.session.commit()
        return PlayerMarketExpireResponse(
            expired_sell_orders=len(expired_sells),
            expired_buy_orders=len(expired_buys),
        )

    # ── Matching engine ────────────────────────────────────────────────────────

    def _match_sell_against_buy_orders(
        self, sell_order: PlayerMarketSellOrder
    ) -> list[PlayerMarketImmediateFill]:
        """When a new sell order arrives, match it against existing buy orders (best bid first)."""
        fills: list[PlayerMarketImmediateFill] = []

        matching_buys = self.session.execute(
            select(PlayerMarketBuyOrder).where(
                PlayerMarketBuyOrder.server_id == self.server_id,
                PlayerMarketBuyOrder.item_key == sell_order.item_key,
                PlayerMarketBuyOrder.unit_price >= sell_order.unit_price,
                PlayerMarketBuyOrder.status.in_(ACTIVE_STATUSES),
                PlayerMarketBuyOrder.remaining_amount > 0,
            )
            .order_by(PlayerMarketBuyOrder.unit_price.desc(), PlayerMarketBuyOrder.created_at.asc())
            .with_for_update()
        ).scalars().all()

        for buy_order in matching_buys:
            if sell_order.remaining_amount <= 0:
                break
            # Prevent self-trading: skip if seller == buyer
            if sell_order.seller_player_name.lower() == buy_order.buyer_player_name.lower():
                logger.warning(
                    "Self-trade blocked: player=%s sell_order=%s buy_order=%s",
                    sell_order.seller_player_name, sell_order.id, buy_order.id,
                )
                continue
            fill_amount = min(sell_order.remaining_amount, buy_order.remaining_amount)
            # Execution price is the buy order's bid (passive side = best for seller)
            execution_price = self._money(buy_order.unit_price)

            # seller_is_active=True: plugin already paid the seller immediately in executeSell;
            # don't create a duplicate sell_proceeds pending delivery.
            fill = self._execute_trade(
                sell_order=sell_order,
                buy_order=buy_order,
                fill_amount=fill_amount,
                execution_price=execution_price,
                seller_is_active=True,
            )
            fills.append(fill)

        if sell_order.remaining_amount == 0:
            sell_order.status = "filled"
            sell_order.filled_at = utc_now()
        elif sell_order.filled_amount > 0:
            sell_order.status = "partially_filled"

        return fills

    def _match_buy_against_sell_orders(
        self, buy_order: PlayerMarketBuyOrder
    ) -> list[PlayerMarketImmediateFill]:
        """When a new buy order arrives, match it against existing sell orders (best ask first)."""
        fills: list[PlayerMarketImmediateFill] = []

        matching_sells = self.session.execute(
            select(PlayerMarketSellOrder).where(
                PlayerMarketSellOrder.server_id == self.server_id,
                PlayerMarketSellOrder.item_key == buy_order.item_key,
                PlayerMarketSellOrder.unit_price <= buy_order.unit_price,
                PlayerMarketSellOrder.status.in_(ACTIVE_STATUSES),
                PlayerMarketSellOrder.remaining_amount > 0,
            )
            .order_by(PlayerMarketSellOrder.unit_price.asc(), PlayerMarketSellOrder.created_at.asc())
            .with_for_update()
        ).scalars().all()

        for sell_order in matching_sells:
            if buy_order.remaining_amount <= 0:
                break
            # Prevent self-trading: skip if seller == buyer
            if sell_order.seller_player_name.lower() == buy_order.buyer_player_name.lower():
                logger.warning(
                    "Self-trade blocked: player=%s sell_order=%s buy_order=%s",
                    buy_order.buyer_player_name, sell_order.id, buy_order.id,
                )
                continue
            fill_amount = min(buy_order.remaining_amount, sell_order.remaining_amount)
            # Execution price is the sell order's ask (passive side = best for buyer)
            execution_price = self._money(sell_order.unit_price)

            # buyer_is_active=True: plugin already gave item + overpay to buyer immediately
            # in executeBuy/executeBuyFromGui; don't create duplicate item_delivery/buy_refund pending.
            fill = self._execute_trade(
                sell_order=sell_order,
                buy_order=buy_order,
                fill_amount=fill_amount,
                execution_price=execution_price,
                buyer_is_active=True,
            )
            fills.append(fill)

        if buy_order.remaining_amount == 0:
            buy_order.status = "filled"
            buy_order.filled_at = utc_now()
        elif buy_order.filled_amount > 0:
            buy_order.status = "partially_filled"

        return fills

    def _execute_trade(
        self,
        sell_order: PlayerMarketSellOrder,
        buy_order: PlayerMarketBuyOrder,
        fill_amount: int,
        execution_price: Decimal,
        seller_is_active: bool = False,
        buyer_is_active: bool = False,
    ) -> PlayerMarketImmediateFill:
        # seller_is_active: the seller just called create_sell_order; the plugin deposits
        #   sell_proceeds immediately from the immediate_fills response, so we must NOT
        #   create a duplicate sell_proceeds pending delivery.
        # buyer_is_active: the buyer just called create_buy_order; the plugin gives the
        #   item and overpay immediately from immediate_fills, so we must NOT create
        #   duplicate item_delivery / buy_refund pending deliveries.
        gross_total = self._money(execution_price * Decimal(fill_amount))
        is_premium = bool((sell_order.metadata_json or {}).get("is_premium"))
        applied_fee = FEE_PERCENT_PREMIUM if is_premium else FEE_PERCENT
        fee_amount = self._money(gross_total * applied_fee / Decimal("100"))
        net_seller_proceeds = self._money(gross_total - fee_amount)

        # Overpay refund: buyer bid >= execution price (possible when sell order matches buy order)
        buyer_spent_per_unit = self._money(buy_order.unit_price)
        overpay_per_unit = buyer_spent_per_unit - execution_price
        funds_returned_to_buyer = self._money(overpay_per_unit * Decimal(fill_amount))
        if funds_returned_to_buyer < 0:
            logger.warning(
                "funds_returned_to_buyer negative (%s) for buy_order=%s sell_order=%s; clamped to 0",
                funds_returned_to_buyer, buy_order.id, sell_order.id,
            )
            funds_returned_to_buyer = Decimal("0")

        trade = PlayerMarketTrade(
            server_id=self.server_id,
            sell_order_id=sell_order.id,
            buy_order_id=buy_order.id,
            seller_player_name=sell_order.seller_player_name,
            buyer_player_name=buy_order.buyer_player_name,
            item_key=sell_order.item_key,
            display_name=sell_order.display_name or buy_order.display_name,
            amount=fill_amount,
            unit_price=execution_price,
            gross_total=gross_total,
            fee_amount=fee_amount,
            net_seller_proceeds=net_seller_proceeds,
            item_stack_base64=sell_order.item_stack_base64,
            metadata_json={"match_type": "auto"},
        )
        self.session.add(trade)
        self.session.flush()

        # Update sell order
        sell_order.remaining_amount -= fill_amount
        sell_order.filled_amount += fill_amount
        if sell_order.remaining_amount == 0:
            sell_order.status = "filled"
            sell_order.filled_at = utc_now()
        elif sell_order.filled_amount > 0:
            sell_order.status = "partially_filled"

        # Update buy order
        buy_order.remaining_amount -= fill_amount
        buy_order.filled_amount += fill_amount
        buy_order.reserved_funds = self._money(
            Decimal(str(buy_order.reserved_funds)) - self._money(buyer_spent_per_unit * Decimal(fill_amount))
        )
        if buy_order.reserved_funds < 0:
            logger.warning(
                "reserved_funds negative (%s) for buy_order=%s; clamped to 0",
                buy_order.reserved_funds, buy_order.id,
            )
            buy_order.reserved_funds = Decimal("0")
        if buy_order.remaining_amount == 0:
            buy_order.status = "filled"
            buy_order.filled_at = utc_now()
        elif buy_order.filled_amount > 0:
            buy_order.status = "partially_filled"

        # Pending delivery: seller receives money.
        # Skip if seller_is_active — plugin deposits immediately from immediate_fills.
        if not seller_is_active:
            self.session.add(PlayerMarketPendingDelivery(
                server_id=self.server_id,
                player_name=sell_order.seller_player_name,
                delivery_type="sell_proceeds",
                trade_id=trade.id,
                sell_order_id=sell_order.id,
                amount_money=net_seller_proceeds,
                item_key=sell_order.item_key,
            ))

        # Pending delivery: buyer receives item.
        # Skip if buyer_is_active — plugin gives item immediately from immediate_fills.
        if not buyer_is_active:
            self.session.add(PlayerMarketPendingDelivery(
                server_id=self.server_id,
                player_name=buy_order.buyer_player_name,
                delivery_type="item_delivery",
                trade_id=trade.id,
                buy_order_id=buy_order.id,
                amount_items=fill_amount,
                item_stack_base64=sell_order.item_stack_base64,
                item_key=sell_order.item_key,
                display_name=sell_order.display_name,
            ))

        # Pending delivery: overpay refund for buyer.
        # Skip if buyer_is_active — plugin deposits immediately from immediate_fills.
        if not buyer_is_active and funds_returned_to_buyer > 0:
            self.session.add(PlayerMarketPendingDelivery(
                server_id=self.server_id,
                player_name=buy_order.buyer_player_name,
                delivery_type="buy_refund",
                trade_id=trade.id,
                buy_order_id=buy_order.id,
                amount_money=funds_returned_to_buyer,
            ))

        # Update price ticker in economy_market_items
        self._update_price_ticker(sell_order.item_key, execution_price, fill_amount)

        # Route fee to seller's nation treasury (if seller belongs to a nation and buyer is in a different nation)
        if fee_amount > 0:
            self._credit_nation_treasury(
                sell_order.seller_player_name, buy_order.buyer_player_name, fee_amount, sell_order.item_key
            )

        return PlayerMarketImmediateFill(
            trade_id=trade.id,
            matched_order_id=buy_order.id if sell_order.id is not None else sell_order.id,
            amount_filled=fill_amount,
            unit_price=float(execution_price),
            gross_total=float(gross_total),
            fee_amount=float(fee_amount),
            net_seller_proceeds=float(net_seller_proceeds),
            item_stack_base64=sell_order.item_stack_base64,
            funds_released_to_seller=float(net_seller_proceeds),
            funds_returned_to_buyer=float(funds_returned_to_buyer),
            seller_player_name=sell_order.seller_player_name or "",
            buyer_player_name=buy_order.buyer_player_name or "",
        )

    # ── Nation treasury ────────────────────────────────────────────────────────

    def _credit_nation_treasury(
        self, seller_player_name: str, buyer_player_name: str, amount: Decimal, item_key: str
    ) -> None:
        """Add market fee to seller's nation treasury.

        Skipped when buyer and seller are in the same nation — prevents the nation
        leader self-fee advantage (fee would just return to their own treasury).
        """
        try:
            def _get_nation_id(nickname: str) -> int | None:
                r = self.session.execute(
                    select(NationMember.nation_id)
                    .join(User, User.id == NationMember.user_id)
                    .join(PlayerAccount, PlayerAccount.user_id == User.id)
                    .where(PlayerAccount.minecraft_nickname_normalized == nickname.lower())
                    .limit(1)
                ).first()
                return r[0] if r else None

            seller_nation_id = _get_nation_id(seller_player_name)
            if seller_nation_id is None:
                return

            buyer_nation_id = _get_nation_id(buyer_player_name)
            if buyer_nation_id is not None and buyer_nation_id == seller_nation_id:
                return

            self.session.add(NationTreasuryTransaction(
                server_id=self.server_id,
                transaction_type="market_fee",
                nation_id=seller_nation_id,
                gross_amount=float(amount),
                fee_amount=0.0,
                net_amount=float(amount),
                comment=f"Рыночный сбор: {item_key}",
                metadata_json={"item_key": item_key, "source": "player_market"},
            ))
        except Exception:
            logger.exception(
                "Failed to credit nation treasury for seller=%s buyer=%s amount=%s",
                seller_player_name, buyer_player_name, amount,
            )

    # ── Economy market price ticker integration ────────────────────────────────

    def _update_price_ticker(self, item_key: str, execution_price: Decimal, amount: int) -> None:
        """Update economy_market_items with the trade's execution price."""
        # Ignore micro-trades that could be used to manipulate the ticker cheaply
        if execution_price * Decimal(amount) < Decimal("10"):
            return

        # economy_market_items uses UPPERCASE material keys
        material_upper = item_key.upper()
        item = self.session.execute(
            select(EconomyMarketItem).where(
                EconomyMarketItem.material == material_upper,
                EconomyMarketItem.server_id == self.server_id,
            )
        ).scalar_one_or_none()

        if item is None:
            return

        # Record the trade as balanced (both demand and supply met)
        amount_d = Decimal(amount)
        item.demand_score = self._money(Decimal(str(item.demand_score or 0)) + amount_d)
        item.supply_score = self._money(Decimal(str(item.supply_score or 0)) + amount_d)

        # Nudge current price toward the actual trade price (weighted average)
        current_buy = Decimal(str(item.current_buy_price or 0))
        if current_buy > 0:
            # Move 10% toward the execution price, scaled by amount (1 stack = full weight)
            weight = min(Decimal(amount) / Decimal("64"), Decimal("1"))
            new_buy = current_buy + (execution_price - current_buy) * weight * Decimal("0.10")
            new_buy = max(new_buy, Decimal("0.01")).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            item.current_buy_price = new_buy

            # Sell price tracks buy price ratio
            if item.base_buy_price and item.base_sell_price:
                ratio = Decimal(str(item.base_sell_price)) / Decimal(str(item.base_buy_price))
                item.current_sell_price = (new_buy * ratio).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _ensure_market_item(self, item_key: str, display_name: str | None, unit_price: float) -> None:
        """Auto-register item in economy_market_items if not present."""
        material_upper = item_key.upper()
        unit = self._money(Decimal(str(unit_price)))
        if unit <= 0:
            return
        base_buy = unit
        base_sell = self._money(unit * Decimal("0.25"))
        stmt = pg_insert(EconomyMarketItem).values(
            server_id=self.server_id,
            material=material_upper,
            display_name=display_name or None,
            base_buy_price=base_buy,
            base_sell_price=base_sell,
            current_buy_price=base_buy,
            current_sell_price=base_sell,
            buy_multiplier=Decimal("1"),
            sell_multiplier=Decimal("1"),
            metadata_json={"source": "player_market"},
        ).on_conflict_do_nothing(index_elements=["server_id", "material"])
        self.session.execute(stmt)
        self.session.flush()

    def _normalize_key(self, value: str) -> str:
        return str(value or "").strip().lower()

    def _money(self, value) -> Decimal:
        return Decimal(str(value or 0)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
