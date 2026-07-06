from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from apps.api.app.core.security import utc_now
from apps.api.app.models.economy_market import EconomyMarketItem, EconomyShopTransaction, PriceHistorySnapshot
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_market import NationMarketListing, NationMarketOrder
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.user import User
from apps.api.app.schemas.economy_market import (
    EconomyMarketPriceListResponse,
    EconomyMarketPriceRead,
    EconomyMarketRecalculateResponse,
    EconomyShopTransactionCreate,
    EconomyShopTransactionRead,
    NationMarketCancelResponse,
    NationMarketListingCreate,
    NationMarketListingListResponse,
    NationMarketListingRead,
    NationMarketPurchaseRequest,
    NationMarketPurchaseResponse,
)
from apps.api.app.utils.normalization import normalize_minecraft_nickname


class EconomyMarketError(Exception):
    pass


class EconomyMarketNotFoundError(EconomyMarketError):
    pass


class EconomyMarketValidationError(EconomyMarketError):
    pass


class EconomyMarketConflictError(EconomyMarketError):
    pass


class EconomyMarketService:
    """Market service used by the game-sync plugin.

    Stage 3/4 notes:
    - EconomyShopGUI transactions are intentionally accepted only through game-auth-secret routes.
    - Shop section/index are stored inside metadata_json to avoid a new migration for existing servers.
    - Prices are updated softly on every transaction and can also be recalculated manually.
    """

    MIN_BUY_MULTIPLIER = Decimal("0.35")
    MAX_BUY_MULTIPLIER = Decimal("5.00")
    MIN_SELL_MULTIPLIER = Decimal("0.25")
    MAX_SELL_MULTIPLIER = Decimal("4.00")
    MAX_SELL_BUY_RATIO = Decimal("0.65")
    MIN_SELL_BUY_RATIO = Decimal("0.05")
    SCORE_DECAY = Decimal("0.92")
    MAX_PRICE_STEP = Decimal("0.08")

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_prices(self) -> EconomyMarketPriceListResponse:
        items = self.session.execute(
            select(EconomyMarketItem)
            .where(EconomyMarketItem.enabled.is_(True))
            .order_by(EconomyMarketItem.material.asc())
        ).scalars().all()
        reads = [self._price_read(item) for item in items]
        return EconomyMarketPriceListResponse(total=len(reads), items=reads)

    def get_price(self, material: str) -> EconomyMarketPriceRead:
        item = self._get_market_item(material)
        if item is None:
            return EconomyMarketPriceRead(material=self._normalize_material(material))
        return self._price_read(item)

    def recalculate_prices(self, decay_scores: bool = True) -> EconomyMarketRecalculateResponse:
        items = self.session.execute(
            select(EconomyMarketItem).where(EconomyMarketItem.enabled.is_(True))
        ).scalars().all()

        changed = 0
        for item in items:
            before = (
                self._money(item.current_buy_price),
                self._money(item.current_sell_price),
                Decimal(str(item.buy_multiplier or 1)),
                Decimal(str(item.sell_multiplier or 1)),
            )
            self._recalculate_item_price(item, decay_scores=decay_scores)
            after = (
                self._money(item.current_buy_price),
                self._money(item.current_sell_price),
                Decimal(str(item.buy_multiplier or 1)),
                Decimal(str(item.sell_multiplier or 1)),
            )
            if after != before:
                changed += 1

        self.session.commit()
        self._try_save_snapshots(items)
        return EconomyMarketRecalculateResponse(total=len(items), changed=changed)

    def _try_save_snapshots(self, items: list[EconomyMarketItem]) -> None:
        last_recorded = self.session.scalar(select(func.max(PriceHistorySnapshot.recorded_at)))
        now = utc_now()
        if last_recorded is not None and (now - last_recorded).total_seconds() < 55 * 60:
            return
        for item in items:
            self.session.add(PriceHistorySnapshot(
                material=item.material,
                buy_price=self._money(item.current_buy_price),
                sell_price=self._money(item.current_sell_price),
                buy_multiplier=Decimal(str(item.buy_multiplier or 1)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
                sell_multiplier=Decimal(str(item.sell_multiplier or 1)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
                recorded_at=now,
            ))
        self.session.commit()

    def record_shop_transaction(self, payload: EconomyShopTransactionCreate) -> EconomyShopTransactionRead:
        material = self._normalize_material(payload.material)
        transaction_type = str(payload.transaction_type or "").strip().lower()
        if not material:
            raise EconomyMarketValidationError("material is required")
        if payload.amount <= 0:
            raise EconomyMarketValidationError("amount must be positive")
        if transaction_type not in {
            "buy", "sell", "buy_screen", "sell_screen", "sell_all_screen", "sell_all_command",
            "buy_stacks_screen", "quick_buy", "quick_sell", "sell_gui_screen", "auto_sell_chest",
            "shopstand_buy_screen", "shopstand_sell_screen",
        }:
            # Unknown EconomyShopGUI transaction types are kept for audit but still handled
            # by prefix checks below. This protects us from future plugin enum additions.
            transaction_type = transaction_type[:32] or "unknown"

        metadata = dict(payload.metadata_json or {})
        if payload.shop_section:
            metadata["shop_section"] = payload.shop_section
        if payload.shop_item_index:
            metadata["shop_item_index"] = payload.shop_item_index
        if payload.display_name:
            metadata["display_name"] = payload.display_name
        if payload.source:
            metadata["source"] = payload.source

        transaction = EconomyShopTransaction(
            player_name=payload.player_name,
            material=material,
            amount=payload.amount,
            transaction_type=transaction_type,
            base_total_price=self._money(payload.base_total_price),
            final_total_price=self._money(payload.final_total_price),
            market_multiplier=Decimal(str(payload.market_multiplier or 1)),
            metadata_json=metadata,
        )
        self.session.add(transaction)

        item = self._get_or_create_market_item_from_transaction(material, payload, metadata, transaction_type)
        if item is not None:
            amount = Decimal(payload.amount)
            if self._is_buy_type(transaction_type):
                item.demand_score = Decimal(str(item.demand_score or 0)) + amount
            elif self._is_sell_type(transaction_type):
                item.supply_score = Decimal(str(item.supply_score or 0)) + amount

            self._merge_market_item_metadata(item, payload, metadata)
            self._recalculate_item_price(item, decay_scores=False, transaction_amount=int(amount))

        self.session.commit()
        self.session.refresh(transaction)
        return EconomyShopTransactionRead(
            id=transaction.id,
            material=transaction.material,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type,
            final_total_price=float(transaction.final_total_price),
            created_at=transaction.created_at,
        )

    def create_nation_listing(self, payload: NationMarketListingCreate) -> NationMarketListingRead:
        nation = self._get_nation_by_slug(payload.nation_slug)
        if nation is None:
            raise EconomyMarketNotFoundError("nation was not found")

        role = self._resolve_role(nation, payload.seller_player_name)
        if role not in {"leader", "officer"}:
            raise EconomyMarketValidationError("only nation leader or officer can create market listing")

        if role != payload.seller_role.lower():
            payload.seller_role = role

        material = self._normalize_material(payload.material)
        anchor = self._money(payload.anchor_unit_price)
        market_item = self._get_market_item(material)
        market_price = self._current_market_buy_price(market_item, anchor)
        server_sell_price = self._current_market_sell_price(market_item)

        relative = Decimal("1")
        if market_price > 0:
            relative = (anchor / market_price).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        min_from_anchor = anchor * Decimal("0.65")
        min_from_sell = server_sell_price * Decimal("1.25")
        min_price = self._money(max(min_from_anchor, min_from_sell, Decimal("0.01")))
        max_price = self._money(anchor * Decimal("3"))
        current = self._clamp_money(market_price * relative, min_price, max_price)

        listing = NationMarketListing(
            nation_id=nation.id,
            seller_player_name=payload.seller_player_name,
            seller_role=role,
            material=material,
            display_name=payload.display_name,
            item_stack_base64=payload.item_stack_base64,
            total_amount=payload.total_amount,
            remaining_amount=payload.total_amount,
            sold_amount=0,
            anchor_unit_price=anchor,
            market_price_at_create=market_price,
            relative_price_multiplier=relative,
            current_unit_price=current,
            min_unit_price=min_price,
            max_unit_price=max_price,
            metadata_json=payload.metadata_json or {},
        )
        self.session.add(listing)
        self.session.commit()
        self.session.refresh(listing)
        return self._listing_read(listing)

    def get_nation_listing(self, listing_id: UUID) -> NationMarketListingRead:
        listing = self.session.execute(
            select(NationMarketListing)
            .options(joinedload(NationMarketListing.nation))
            .where(NationMarketListing.id == listing_id)
        ).unique().scalar_one_or_none()
        if listing is None:
            raise EconomyMarketNotFoundError("market listing was not found")
        self._refresh_listing_price(listing)
        self.session.commit()
        return self._listing_read(listing)

    def list_nation_market_listings(
        self,
        nation_slug: str | None = None,
        include_inactive: bool = False,
        limit: int = 100,
    ) -> NationMarketListingListResponse:
        stmt = select(NationMarketListing).options(joinedload(NationMarketListing.nation))
        if not include_inactive:
            stmt = stmt.where(NationMarketListing.status == "active", NationMarketListing.remaining_amount > 0)
        if nation_slug:
            nation = self._get_nation_by_slug(nation_slug)
            if nation is None:
                raise EconomyMarketNotFoundError("nation was not found")
            stmt = stmt.where(NationMarketListing.nation_id == nation.id)
        stmt = stmt.order_by(NationMarketListing.created_at.desc()).limit(min(max(limit, 1), 200))

        listings = self.session.execute(stmt).unique().scalars().all()
        reads = [self._refresh_listing_price(listing) for listing in listings]
        self.session.commit()
        return NationMarketListingListResponse(total=len(reads), items=[self._listing_read(item) for item in listings])

    def purchase_nation_listing(
        self,
        listing_id: UUID,
        payload: NationMarketPurchaseRequest,
        fee_percent: float = 3.0,
        allowed_price_diff_percent: float = 2.0,
    ) -> NationMarketPurchaseResponse:
        listing = self.session.execute(
            select(NationMarketListing)
            .where(NationMarketListing.id == listing_id)
            .with_for_update(of=NationMarketListing)
        ).scalar_one_or_none()
        if listing is None:
            raise EconomyMarketNotFoundError("market listing was not found")

        if self._same_player(payload.buyer_player_name, listing.seller_player_name):
            raise EconomyMarketConflictError("Нельзя покупать свой собственный лот.")

        if payload.amount <= 0:
            raise EconomyMarketValidationError("purchase amount must be positive")
        if listing.status != "active" or listing.remaining_amount <= 0:
            raise EconomyMarketConflictError("market listing is not active")
        if payload.amount > listing.remaining_amount:
            raise EconomyMarketConflictError("not enough items left in listing")

        self._refresh_listing_price(listing)
        unit_price = self._money(listing.current_unit_price)
        expected = self._money(payload.expected_unit_price)
        if expected <= 0:
            raise EconomyMarketValidationError("expected price must be positive")
        diff_percent = abs(unit_price - expected) / expected * Decimal("100")
        if diff_percent > Decimal(str(allowed_price_diff_percent)):
            raise EconomyMarketConflictError("market price changed, refresh listing and try again")

        amount = payload.amount
        gross_total = self._money(unit_price * Decimal(amount))
        fee_amount = self._money(gross_total * Decimal(str(fee_percent)) / Decimal("100"))
        net_total = self._money(gross_total - fee_amount)

        listing.remaining_amount -= amount
        listing.sold_amount += amount
        if listing.remaining_amount <= 0:
            listing.status = "sold_out"
            listing.sold_out_at = utc_now()

        order = NationMarketOrder(
            listing_id=listing.id,
            nation_id=listing.nation_id,
            buyer_player_name=payload.buyer_player_name,
            amount=amount,
            unit_price=unit_price,
            gross_total=gross_total,
            fee_amount=fee_amount,
            net_total=net_total,
            metadata_json={"source": "voidrp_nation_market"},
        )
        self.session.add(order)

        stat = self._get_or_create_nation_stat(listing.nation_id)
        stat.treasury_balance = self._money(Decimal(str(stat.treasury_balance or 0)) + net_total)

        self.session.add(
            NationTreasuryTransaction(
                transaction_type="nation_market_sale",
                nation_id=listing.nation_id,
                gross_amount=gross_total,
                fee_amount=fee_amount,
                net_amount=net_total,
                comment=f"Продажа на рынке государств: {listing.material} x{amount}",
                metadata_json={
                    "listing_id": str(listing.id),
                    "buyer_player_name": payload.buyer_player_name,
                    "seller_player_name": listing.seller_player_name,
                    "unit_price": float(unit_price),
                    "amount": amount,
                },
            )
        )

        self.session.commit()
        self.session.refresh(listing)
        return NationMarketPurchaseResponse(
            message="Nation market purchase completed.",
            listing=self._listing_read(listing),
            purchased_amount=amount,
            unit_price=float(unit_price),
            gross_total=float(gross_total),
            fee_amount=float(fee_amount),
            net_total=float(net_total),
            item_stack_base64=listing.item_stack_base64,
        )

    def cancel_nation_listing(self, listing_id: UUID, requester_player_name: str) -> NationMarketCancelResponse:
        listing = self.session.execute(
            select(NationMarketListing)
            .where(NationMarketListing.id == listing_id)
            .with_for_update(of=NationMarketListing)
        ).scalar_one_or_none()
        if listing is None:
            raise EconomyMarketNotFoundError("market listing was not found")
        if listing.status != "active":
            raise EconomyMarketConflictError("market listing is not active")

        role = self._resolve_role(listing.nation, requester_player_name)
        if role not in {"leader", "officer"}:
            raise EconomyMarketValidationError("only nation leader or officer can cancel market listing")

        returned = listing.remaining_amount
        listing.status = "cancelled"
        listing.cancelled_at = utc_now()
        self.session.commit()
        self.session.refresh(listing)
        return NationMarketCancelResponse(
            message="Nation market listing cancelled.",
            listing=self._listing_read(listing),
            returned_amount=returned,
            item_stack_base64=listing.item_stack_base64,
        )

    def _price_read(self, item: EconomyMarketItem) -> EconomyMarketPriceRead:
        metadata = item.metadata_json or {}
        return EconomyMarketPriceRead(
            material=item.material,
            display_name=item.display_name,
            group_key=item.group_key,
            base_buy_price=float(item.base_buy_price or 0),
            base_sell_price=float(item.base_sell_price or 0),
            current_buy_price=float(item.current_buy_price or 0),
            current_sell_price=float(item.current_sell_price or 0),
            buy_multiplier=float(item.buy_multiplier or 1),
            sell_multiplier=float(item.sell_multiplier or 1),
            demand_score=float(item.demand_score or 0),
            supply_score=float(item.supply_score or 0),
            enabled=item.enabled,
            updated_at=item.updated_at,
            shop_section=self._metadata_string(metadata, "shop_section"),
            shop_item_index=self._metadata_string(metadata, "shop_item_index"),
            source=self._metadata_string(metadata, "source"),
        )

    def _listing_read(self, listing: NationMarketListing) -> NationMarketListingRead:
        nation = listing.nation
        return NationMarketListingRead(
            id=listing.id,
            nation_slug=nation.slug,
            nation_title=nation.title,
            nation_tag=nation.tag,
            seller_player_name=listing.seller_player_name,
            seller_role=listing.seller_role,
            material=listing.material,
            display_name=listing.display_name,
            item_stack_base64=listing.item_stack_base64,
            total_amount=listing.total_amount,
            remaining_amount=listing.remaining_amount,
            sold_amount=listing.sold_amount,
            anchor_unit_price=float(listing.anchor_unit_price),
            market_price_at_create=float(listing.market_price_at_create),
            relative_price_multiplier=float(listing.relative_price_multiplier),
            current_unit_price=float(listing.current_unit_price),
            min_unit_price=float(listing.min_unit_price),
            max_unit_price=float(listing.max_unit_price),
            status=listing.status,
            pricing_mode=listing.pricing_mode,
            created_at=listing.created_at,
            updated_at=listing.updated_at,
        )

    def _refresh_listing_price(self, listing: NationMarketListing) -> NationMarketListing:
        item = self._get_market_item(listing.material)
        market_price = self._current_market_buy_price(item, Decimal(str(listing.anchor_unit_price)))
        calculated = market_price * Decimal(str(listing.relative_price_multiplier or 1))
        listing.current_unit_price = self._clamp_money(
            calculated,
            Decimal(str(listing.min_unit_price or 0)),
            Decimal(str(listing.max_unit_price or 0)),
        )
        return listing

    def _get_or_create_market_item_from_transaction(
        self,
        material: str,
        payload: EconomyShopTransactionCreate,
        metadata: dict,
        transaction_type: str,
    ) -> EconomyMarketItem | None:
        item = self._get_market_item(material)
        amount = Decimal(max(payload.amount, 1))
        final_total = self._money(payload.final_total_price)
        unit = self._money(final_total / amount) if final_total > 0 else Decimal("0")

        if item is None:
            # Do not create zero-price noise records for sell-all/multi events without exact price.
            if unit <= 0:
                return None
            if self._is_buy_type(transaction_type):
                base_buy = unit
                base_sell = self._money(unit * Decimal("0.25"))
            elif self._is_sell_type(transaction_type):
                base_sell = unit
                base_buy = self._money(max(unit * Decimal("4"), unit))
            else:
                base_buy = unit
                base_sell = self._money(unit * Decimal("0.25"))

            stmt = pg_insert(EconomyMarketItem).values(
                material=material,
                display_name=payload.display_name or material,
                base_buy_price=base_buy,
                base_sell_price=base_sell,
                current_buy_price=base_buy,
                current_sell_price=base_sell,
                buy_multiplier=Decimal("1"),
                sell_multiplier=Decimal("1"),
                metadata_json={},
            ).on_conflict_do_nothing(index_elements=["material"])
            self.session.execute(stmt)
            self.session.flush()
            item = self._get_market_item(material)
            if item is None:
                return None

        # Auto-fill missing base prices when the first precise transaction arrives later.
        if unit > 0:
            if self._is_buy_type(transaction_type) and self._money(item.base_buy_price) <= 0:
                item.base_buy_price = unit
            if self._is_sell_type(transaction_type) and self._money(item.base_sell_price) <= 0:
                item.base_sell_price = unit
            if self._money(item.base_buy_price) <= 0 and self._money(item.base_sell_price) > 0:
                item.base_buy_price = self._money(Decimal(str(item.base_sell_price)) * Decimal("4"))
            if self._money(item.base_sell_price) <= 0 and self._money(item.base_buy_price) > 0:
                item.base_sell_price = self._money(Decimal(str(item.base_buy_price)) * Decimal("0.25"))

        return item

    def _merge_market_item_metadata(
        self,
        item: EconomyMarketItem,
        payload: EconomyShopTransactionCreate,
        metadata: dict,
    ) -> None:
        current = dict(item.metadata_json or {})
        for key in ("shop_section", "shop_item_index", "source"):
            value = metadata.get(key)
            if value is not None and str(value).strip():
                current[key] = str(value).strip()
        if payload.display_name and not item.display_name:
            item.display_name = payload.display_name
        if payload.display_name:
            current["display_name"] = payload.display_name
        current["last_transaction_source"] = metadata.get("source", "economyshopgui")
        current["last_transaction_at"] = utc_now().isoformat()
        item.metadata_json = current

    def _recalculate_item_price(self, item: EconomyMarketItem, decay_scores: bool, transaction_amount: int | None = None) -> None:
        base_buy = self._money(item.base_buy_price)
        base_sell = self._money(item.base_sell_price)
        if base_buy <= 0 and base_sell > 0:
            base_buy = self._money(base_sell * Decimal("4"))
            item.base_buy_price = base_buy
        if base_sell <= 0 and base_buy > 0:
            base_sell = self._money(base_buy * Decimal("0.25"))
            item.base_sell_price = base_sell
        if base_buy <= 0:
            return

        demand = Decimal(str(item.demand_score or 0))
        supply = Decimal(str(item.supply_score or 0))
        volume = max(demand + supply, Decimal("1"))
        pressure = (demand - supply) / (volume + Decimal("64"))
        if pressure > Decimal("1"):
            pressure = Decimal("1")
        if pressure < Decimal("-1"):
            pressure = Decimal("-1")

        old_buy_multiplier = Decimal(str(item.buy_multiplier or 1))
        old_sell_multiplier = Decimal(str(item.sell_multiplier or 1))

        # Scale price step by transaction size so 1 item bought 64 times ≠ 64 items bought once.
        # One stack (64 items) = full step; fewer items = proportionally smaller step.
        if transaction_amount is not None:
            amount_factor = self._clamp_decimal(
                Decimal(str(transaction_amount)) / Decimal("64"),
                Decimal("0"),
                Decimal("1"),
            )
        else:
            amount_factor = Decimal("1")

        buy_step = self._clamp_decimal(pressure * Decimal("0.08") * amount_factor, -self.MAX_PRICE_STEP, self.MAX_PRICE_STEP)
        sell_step = self._clamp_decimal(pressure * Decimal("0.06") * amount_factor, -self.MAX_PRICE_STEP, self.MAX_PRICE_STEP)

        new_buy_multiplier = self._clamp_decimal(
            old_buy_multiplier * (Decimal("1") + buy_step),
            self.MIN_BUY_MULTIPLIER,
            self.MAX_BUY_MULTIPLIER,
        )
        new_sell_multiplier = self._clamp_decimal(
            old_sell_multiplier * (Decimal("1") + sell_step),
            self.MIN_SELL_MULTIPLIER,
            self.MAX_SELL_MULTIPLIER,
        )

        current_buy = self._money(base_buy * new_buy_multiplier)
        current_sell = self._money(base_sell * new_sell_multiplier)

        max_sell = self._money(current_buy * self.MAX_SELL_BUY_RATIO)
        min_sell = self._money(current_buy * self.MIN_SELL_BUY_RATIO)
        if current_sell > max_sell:
            current_sell = max_sell
        if base_sell > 0 and current_sell < min_sell:
            current_sell = min_sell

        item.buy_multiplier = new_buy_multiplier.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        item.sell_multiplier = new_sell_multiplier.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        item.current_buy_price = current_buy
        item.current_sell_price = current_sell

        if decay_scores:
            item.demand_score = (demand * self.SCORE_DECAY).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            item.supply_score = (supply * self.SCORE_DECAY).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def _get_market_item(self, material: str) -> EconomyMarketItem | None:
        normalized = self._normalize_material(material)
        return self.session.execute(
            select(EconomyMarketItem).where(EconomyMarketItem.material == normalized)
        ).scalar_one_or_none()

    def _get_nation_by_slug(self, slug: str) -> Nation | None:
        return self.session.execute(
            select(Nation)
            .options(joinedload(Nation.members).joinedload(NationMember.user).joinedload(User.player_account))
            .where(Nation.slug == slug)
        ).unique().scalar_one_or_none()

    def _resolve_role(self, nation: Nation, minecraft_nickname: str) -> str | None:
        _raw, normalized = normalize_minecraft_nickname(minecraft_nickname)
        for member in nation.members or []:
            user = member.user
            account = user.player_account if user is not None else None
            if account is not None and account.minecraft_nickname_normalized == normalized:
                return member.role
        return None

    def _same_player(self, left: str | None, right: str | None) -> bool:
        if not left or not right:
            return False
        _left_raw, left_normalized = normalize_minecraft_nickname(left)
        _right_raw, right_normalized = normalize_minecraft_nickname(right)
        return bool(left_normalized) and left_normalized == right_normalized

    def _get_or_create_nation_stat(self, nation_id) -> NationStat:
        stat = self.session.execute(select(NationStat).where(NationStat.nation_id == nation_id)).scalar_one_or_none()
        if stat is None:
            stat = NationStat(nation_id=nation_id)
            self.session.add(stat)
            self.session.flush()
        return stat

    def _current_market_buy_price(self, item: EconomyMarketItem | None, fallback: Decimal) -> Decimal:
        if item is None:
            return self._money(fallback)
        price = Decimal(str(item.current_buy_price or 0))
        return self._money(price if price > 0 else fallback)

    def _current_market_sell_price(self, item: EconomyMarketItem | None) -> Decimal:
        if item is None:
            return Decimal("0")
        return self._money(Decimal(str(item.current_sell_price or 0)))

    def _is_buy_type(self, transaction_type: str) -> bool:
        value = str(transaction_type or "").lower()
        return "buy" in value and "sell" not in value

    def _is_sell_type(self, transaction_type: str) -> bool:
        return "sell" in str(transaction_type or "").lower()

    def _metadata_string(self, metadata: dict, key: str) -> str | None:
        value = metadata.get(key)
        if value is None:
            return None
        result = str(value).strip()
        return result or None

    def _normalize_material(self, value: str) -> str:
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

    def _clamp_decimal(self, value: Decimal, min_value: Decimal, max_value: Decimal) -> Decimal:
        if value < min_value:
            return min_value
        if value > max_value:
            return max_value
        return value
