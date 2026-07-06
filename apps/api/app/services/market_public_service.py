from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.core.security import utc_now
from apps.api.app.models.economy_market import EconomyMarketItem, EconomyShopTransaction, PriceHistorySnapshot
from apps.api.app.models.nation_market import NationMarketListing, NationMarketOrder
from apps.api.app.schemas.market_public import (
    AdminMarketActionResponse,
    AdminMarketItemPatch,
    AdminMarketRecalculateResponse,
    PriceHistoryPoint,
    PriceHistoryResponse,
    PublicMarketItemListResponse,
    PublicMarketItemRead,
    PublicMarketListingListResponse,
    PublicMarketListingRead,
    PublicMarketSummaryResponse,
    PublicMarketTransactionListResponse,
    PublicMarketTransactionRead,
)
from apps.api.app.services.economy_market_service import EconomyMarketNotFoundError, EconomyMarketService


class MarketPublicService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def list_items(
        self,
        q: str | None = None,
        group_key: str | None = None,
        include_disabled: bool = False,
        sort: str = "material",
        direction: str = "asc",
        limit: int = 200,
    ) -> PublicMarketItemListResponse:
        stmt = select(EconomyMarketItem).where(EconomyMarketItem.server_id == self.server_id)
        if not include_disabled:
            stmt = stmt.where(EconomyMarketItem.enabled.is_(True))
        if q:
            like = f"%{q.strip().upper()}%"
            stmt = stmt.where(
                EconomyMarketItem.material.ilike(like) | EconomyMarketItem.display_name.ilike(f"%{q.strip()}%")
            )
        if group_key:
            stmt = stmt.where(EconomyMarketItem.group_key == group_key.strip())

        order_column = {
            "material": EconomyMarketItem.material,
            "buy": EconomyMarketItem.current_buy_price,
            "sell": EconomyMarketItem.current_sell_price,
            "demand": EconomyMarketItem.demand_score,
            "supply": EconomyMarketItem.supply_score,
            "updated": EconomyMarketItem.updated_at,
        }.get(str(sort or "material").lower(), EconomyMarketItem.material)
        if str(direction or "asc").lower() == "desc":
            order_column = order_column.desc()
        else:
            order_column = order_column.asc()

        items = self.session.execute(
            stmt.order_by(order_column).limit(min(max(limit, 1), 500))
        ).scalars().all()
        reads = [self._item_read(item) for item in items]
        return PublicMarketItemListResponse(total=len(reads), items=reads)

    def get_item(self, material: str) -> PublicMarketItemRead:
        item = self._get_item(material)
        if item is None:
            raise EconomyMarketNotFoundError("market item was not found")
        return self._item_read(item)

    def get_summary(self) -> PublicMarketSummaryResponse:
        now = utc_now()
        since = now - timedelta(hours=24)
        active_items = self.session.scalar(
            select(func.count(EconomyMarketItem.id)).where(
                EconomyMarketItem.server_id == self.server_id,
                EconomyMarketItem.enabled.is_(True),
            )
        ) or 0
        total_items = self.session.scalar(
            select(func.count(EconomyMarketItem.id)).where(EconomyMarketItem.server_id == self.server_id)
        ) or 0
        active_nation_listings = self.session.scalar(
            select(func.count(NationMarketListing.id)).where(
                NationMarketListing.server_id == self.server_id,
                NationMarketListing.status == "active",
                NationMarketListing.remaining_amount > 0,
            )
        ) or 0
        stock_value = self.session.scalar(
            select(func.coalesce(func.sum(NationMarketListing.current_unit_price * NationMarketListing.remaining_amount), 0)).where(
                NationMarketListing.server_id == self.server_id,
                NationMarketListing.status == "active",
                NationMarketListing.remaining_amount > 0,
            )
        ) or Decimal("0")
        shop_tx_count = self.session.scalar(
            select(func.count(EconomyShopTransaction.id)).where(
                EconomyShopTransaction.server_id == self.server_id,
                EconomyShopTransaction.created_at >= since,
            )
        ) or 0
        shop_volume = self.session.scalar(
            select(func.coalesce(func.sum(EconomyShopTransaction.final_total_price), 0)).where(
                EconomyShopTransaction.server_id == self.server_id,
                EconomyShopTransaction.created_at >= since,
            )
        ) or Decimal("0")
        nation_orders = self.session.scalar(
            select(func.count(NationMarketOrder.id)).where(
                NationMarketOrder.server_id == self.server_id,
                NationMarketOrder.created_at >= since,
            )
        ) or 0
        nation_volume = self.session.scalar(
            select(func.coalesce(func.sum(NationMarketOrder.gross_total), 0)).where(
                NationMarketOrder.server_id == self.server_id,
                NationMarketOrder.created_at >= since,
            )
        ) or Decimal("0")

        top_demand = self.session.execute(
            select(EconomyMarketItem)
            .where(EconomyMarketItem.server_id == self.server_id, EconomyMarketItem.enabled.is_(True))
            .order_by(EconomyMarketItem.demand_score.desc())
            .limit(6)
        ).scalars().all()
        top_supply = self.session.execute(
            select(EconomyMarketItem)
            .where(EconomyMarketItem.server_id == self.server_id, EconomyMarketItem.enabled.is_(True))
            .order_by(EconomyMarketItem.supply_score.desc())
            .limit(6)
        ).scalars().all()

        return PublicMarketSummaryResponse(
            total_items=int(total_items),
            active_items=int(active_items),
            active_nation_listings=int(active_nation_listings),
            nation_market_stock_value=float(self._money(stock_value)),
            shop_transactions_24h=int(shop_tx_count),
            shop_volume_24h=float(self._money(shop_volume)),
            nation_orders_24h=int(nation_orders),
            nation_volume_24h=float(self._money(nation_volume)),
            top_demand_items=[self._item_read(item) for item in top_demand],
            top_supply_items=[self._item_read(item) for item in top_supply],
            updated_at=now,
        )

    def list_nation_listings(
        self,
        q: str | None = None,
        nation_slug: str | None = None,
        material: str | None = None,
        limit: int = 100,
    ) -> PublicMarketListingListResponse:
        stmt = select(NationMarketListing).options(joinedload(NationMarketListing.nation)).where(
            NationMarketListing.server_id == self.server_id,
            NationMarketListing.status == "active",
            NationMarketListing.remaining_amount > 0,
        )
        if nation_slug:
            stmt = stmt.join(NationMarketListing.nation).where(NationMarketListing.nation.has(slug=nation_slug.strip()))
        if material:
            stmt = stmt.where(NationMarketListing.material == self._normalize_material(material))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                NationMarketListing.material.ilike(f"%{q.strip().upper()}%")
                | NationMarketListing.display_name.ilike(like)
                | NationMarketListing.seller_player_name.ilike(like)
            )
        listings = self.session.execute(
            stmt.order_by(NationMarketListing.updated_at.desc()).limit(min(max(limit, 1), 200))
        ).unique().scalars().all()
        for listing in listings:
            self._refresh_listing_price(listing)
        self.session.commit()
        return PublicMarketListingListResponse(total=len(listings), items=[self._listing_read(item) for item in listings])

    def list_transactions(self, material: str | None = None, limit: int = 50) -> PublicMarketTransactionListResponse:
        stmt = select(EconomyShopTransaction).where(EconomyShopTransaction.server_id == self.server_id)
        if material:
            stmt = stmt.where(EconomyShopTransaction.material == self._normalize_material(material))
        transactions = self.session.execute(
            stmt.order_by(EconomyShopTransaction.created_at.desc()).limit(min(max(limit, 1), 200))
        ).scalars().all()
        return PublicMarketTransactionListResponse(
            total=len(transactions),
            items=[self._transaction_read(item) for item in transactions],
        )

    def get_price_history(self, material: str, days: int = 30) -> PriceHistoryResponse:
        normalized = self._normalize_material(material)
        item = self._get_item(normalized)
        if item is None:
            raise EconomyMarketNotFoundError("market item was not found")

        days = max(1, min(days, 90))
        since = utc_now() - timedelta(days=days)
        snaps = self.session.execute(
            select(PriceHistorySnapshot)
            .where(
                PriceHistorySnapshot.server_id == self.server_id,
                PriceHistorySnapshot.material == normalized,
                PriceHistorySnapshot.recorded_at >= since,
            )
            .order_by(PriceHistorySnapshot.recorded_at.asc())
        ).scalars().all()

        points = [
            PriceHistoryPoint(
                recorded_at=snap.recorded_at,
                buy_price=float(self._money(snap.buy_price)),
                sell_price=float(self._money(snap.sell_price)),
            )
            for snap in snaps
        ]
        return PriceHistoryResponse(material=normalized, total=len(points), points=points)

    def patch_item(self, material: str, payload: AdminMarketItemPatch) -> AdminMarketActionResponse:
        item = self._get_item(material)
        if item is None:
            raise EconomyMarketNotFoundError("market item was not found")

        if payload.enabled is not None:
            item.enabled = payload.enabled
        if payload.display_name is not None:
            item.display_name = payload.display_name.strip() or None
        if payload.group_key is not None:
            item.group_key = payload.group_key.strip() or "default"
        if payload.base_buy_price is not None:
            item.base_buy_price = self._money(payload.base_buy_price)
        if payload.base_sell_price is not None:
            item.base_sell_price = self._money(payload.base_sell_price)
        if payload.buy_multiplier is not None:
            item.buy_multiplier = Decimal(str(payload.buy_multiplier)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if payload.sell_multiplier is not None:
            item.sell_multiplier = Decimal(str(payload.sell_multiplier)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if payload.current_buy_price is not None:
            item.current_buy_price = self._money(payload.current_buy_price)
        if payload.current_sell_price is not None:
            item.current_sell_price = self._money(payload.current_sell_price)
        if payload.reset_scores:
            item.demand_score = Decimal("0")
            item.supply_score = Decimal("0")
        if payload.reset_to_base:
            item.buy_multiplier = Decimal("1")
            item.sell_multiplier = Decimal("1")
            item.current_buy_price = self._money(item.base_buy_price)
            item.current_sell_price = self._money(item.base_sell_price)
            item.demand_score = Decimal("0")
            item.supply_score = Decimal("0")

        metadata = dict(item.metadata_json or {})
        if payload.admin_note is not None:
            metadata["admin_note"] = payload.admin_note.strip()
            metadata["admin_note_updated_at"] = utc_now().isoformat()
        metadata["last_admin_update_at"] = utc_now().isoformat()
        item.metadata_json = metadata

        self.session.commit()
        self.session.refresh(item)
        return AdminMarketActionResponse(message="Market item updated.", item=self._item_read(item))

    def enable_item(self, material: str, enabled: bool) -> AdminMarketActionResponse:
        return self.patch_item(material, AdminMarketItemPatch(enabled=enabled))

    def reset_item(self, material: str) -> AdminMarketActionResponse:
        return self.patch_item(material, AdminMarketItemPatch(reset_to_base=True, admin_note="Reset to base by admin"))

    def recalculate(self, decay_scores: bool = True) -> AdminMarketRecalculateResponse:
        result = EconomyMarketService(self.session, self.server_id).recalculate_prices(decay_scores=decay_scores)
        return AdminMarketRecalculateResponse(total=result.total, changed=result.changed)

    def _item_read(self, item: EconomyMarketItem) -> PublicMarketItemRead:
        base_buy = self._money(item.base_buy_price)
        base_sell = self._money(item.base_sell_price)
        current_buy = self._money(item.current_buy_price)
        current_sell = self._money(item.current_sell_price)
        trend = Decimal("0") if base_buy <= 0 else ((current_buy - base_buy) / base_buy * Decimal("100"))
        spread = Decimal("0") if current_buy <= 0 else ((current_buy - current_sell) / current_buy * Decimal("100"))
        demand = Decimal(str(item.demand_score or 0))
        supply = Decimal(str(item.supply_score or 0))
        demand_state = "stable"
        if demand > supply * Decimal("1.35") + Decimal("16"):
            demand_state = "high_demand"
        elif supply > demand * Decimal("1.35") + Decimal("16"):
            demand_state = "oversupply"

        metadata = item.metadata_json or {}
        return PublicMarketItemRead(
            material=item.material,
            display_name=item.display_name,
            group_key=item.group_key,
            base_buy_price=float(base_buy),
            base_sell_price=float(base_sell),
            current_buy_price=float(current_buy),
            current_sell_price=float(current_sell),
            buy_multiplier=float(item.buy_multiplier or 1),
            sell_multiplier=float(item.sell_multiplier or 1),
            demand_score=float(item.demand_score or 0),
            supply_score=float(item.supply_score or 0),
            trend_percent=float(self._money(trend)),
            spread_percent=float(self._money(spread)),
            demand_state=demand_state,
            shop_section=self._metadata_string(metadata, "shop_section"),
            shop_item_index=self._metadata_string(metadata, "shop_item_index"),
            enabled=item.enabled,
            updated_at=item.updated_at,
        )

    def _listing_read(self, listing: NationMarketListing) -> PublicMarketListingRead:
        nation = listing.nation
        return PublicMarketListingRead(
            id=listing.id,
            nation_slug=nation.slug if nation else "",
            nation_title=nation.title if nation else "Государство",
            nation_tag=nation.tag if nation else "---",
            seller_player_name=listing.seller_player_name,
            seller_role=listing.seller_role,
            material=listing.material,
            display_name=listing.display_name,
            total_amount=listing.total_amount,
            remaining_amount=listing.remaining_amount,
            sold_amount=listing.sold_amount,
            current_unit_price=float(self._money(listing.current_unit_price)),
            anchor_unit_price=float(self._money(listing.anchor_unit_price)),
            relative_price_multiplier=float(listing.relative_price_multiplier or 1),
            status=listing.status,
            pricing_mode=listing.pricing_mode,
            created_at=listing.created_at,
            updated_at=listing.updated_at,
        )

    def _transaction_read(self, transaction: EconomyShopTransaction) -> PublicMarketTransactionRead:
        amount = max(int(transaction.amount or 0), 1)
        total = self._money(transaction.final_total_price)
        return PublicMarketTransactionRead(
            id=transaction.id,
            player_name=transaction.player_name,
            material=transaction.material,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type,
            final_total_price=float(total),
            unit_price=float(self._money(total / Decimal(amount))),
            created_at=transaction.created_at,
        )

    def _refresh_listing_price(self, listing: NationMarketListing) -> None:
        item = self._get_item(listing.material)
        fallback = self._money(listing.anchor_unit_price)
        market_price = self._money(item.current_buy_price if item is not None else fallback)
        if market_price <= 0:
            market_price = fallback
        calculated = market_price * Decimal(str(listing.relative_price_multiplier or 1))
        listing.current_unit_price = self._clamp_money(
            calculated,
            self._money(listing.min_unit_price),
            self._money(listing.max_unit_price),
        )

    def _get_item(self, material: str) -> EconomyMarketItem | None:
        normalized = self._normalize_material(material)
        if not normalized:
            return None
        return self.session.execute(
            select(EconomyMarketItem).where(
                EconomyMarketItem.material == normalized,
                EconomyMarketItem.server_id == self.server_id,
            )
        ).scalar_one_or_none()

    def _metadata_string(self, metadata: dict, key: str) -> str | None:
        value = metadata.get(key)
        if value is None:
            return None
        result = str(value).strip()
        return result or None

    def _normalize_material(self, value: str | None) -> str:
        return str(value or "").strip().upper()

    def _money(self, value) -> Decimal:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _clamp_money(self, value: Decimal, min_value: Decimal, max_value: Decimal) -> Decimal:
        result = self._money(value)
        if min_value > 0 and result < min_value:
            result = self._money(min_value)
        if max_value > 0 and result > max_value:
            result = self._money(max_value)
        return result
