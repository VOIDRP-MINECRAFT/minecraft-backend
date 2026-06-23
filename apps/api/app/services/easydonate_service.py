from __future__ import annotations

import hashlib
import hmac
import logging
import time

import httpx

from apps.api.app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_BASE = "https://easydonate.ru/api/v3"
_HEADERS = {"User-Agent": "VoidRP/1.0"}

# Simple process-level cache: key → (value, expires_at)
_cache: dict[str, tuple[object, float]] = {}


def _cache_get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: object, ttl: int) -> None:
    _cache[key] = (value, time.monotonic() + ttl)


class EasyDonateError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class EasyDonateService:
    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._key = s.easydonate_shop_key
        self._server_id = s.easydonate_server_id
        self._headers = {**_HEADERS, "Shop-Key": self._key}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{_BASE}{path}"
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=self._headers, params=params)
            if r.status_code == 429:
                raise EasyDonateError(429, "EasyDonate: слишком много запросов (rate limit). Попробуйте позже.")
            try:
                data = r.json()
            except Exception:
                r.raise_for_status()
                raise
        if not data.get("success"):
            msg = data.get("response") if isinstance(data.get("response"), str) else str(data)
            code = data.get("error_code", 0)
            logger.error("EasyDonate error path=%s code=%s msg=%s", path, code, msg)
            raise EasyDonateError(code, msg)
        return data["response"]

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{_BASE}{path}"
        with httpx.Client(timeout=10) as client:
            r = client.post(url, headers=self._headers, data=payload)
            r.raise_for_status()
            data = r.json()
        if not data.get("success"):
            err = data.get("error", {})
            raise EasyDonateError(err.get("code", 0), err.get("message", "unknown error"))
        return data["response"]

    def get_products(self) -> list:
        key = f"products:{self._server_id}"
        cached = _cache_get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        result = self._get("/shop/products", params={"server_id": self._server_id})
        _cache_set(key, result, ttl=300)
        return result

    def get_product(self, product_id: int) -> dict:
        key = f"product:{product_id}"
        cached = _cache_get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        result = self._get(f"/shop/product/{product_id}")
        _cache_set(key, result, ttl=300)
        return result

    def get_servers(self) -> list:
        cached = _cache_get("servers")
        if cached is not None:
            return cached  # type: ignore[return-value]
        result = self._get("/shop/servers")
        _cache_set("servers", result, ttl=300)
        return result

    def create_payment(
        self,
        customer: str,
        products: dict[int, int],
        email: str | None = None,
        coupon: str | None = None,
        success_url: str | None = None,
    ) -> dict:
        import json as _json
        params: dict = {
            "customer": customer,
            "server_id": self._server_id,
            "products": _json.dumps(products, separators=(",", ":")),
        }
        if email:
            params["email"] = email
        if coupon:
            params["coupon"] = coupon
        if success_url:
            params["success_url"] = success_url
        return self._get("/shop/payment/create", params=params)

    def get_last_payments(self) -> list:
        cached = _cache_get("last_payments")
        if cached is not None:
            return cached  # type: ignore[return-value]
        result = self._get("/shop/payments", params={"paginate": 10, "page": 1})
        data = result.get("data", result) if isinstance(result, dict) else result
        _cache_set("last_payments", data, ttl=60)
        return data

    def get_payments_paginated(self, page: int = 1, per_page: int = 20) -> dict:
        result = self._get("/shop/payments", params={"paginate": per_page, "page": page})
        return result if isinstance(result, dict) else {"data": result, "total": len(result), "current_page": 1, "last_page": 1, "per_page": per_page}

    def get_admin_overview(self) -> dict:
        """Single call that returns stats + first-page payments + products. Cached 5 min."""
        cached = _cache_get("admin_overview")
        if cached is not None:
            return cached  # type: ignore[return-value]
        from datetime import datetime

        # One payments request + one products request
        pay_result = self._get("/shop/payments", params={"paginate": 50, "page": 1})
        products = self.get_products()  # has its own cache

        data = pay_result.get("data", []) if isinstance(pay_result, dict) else pay_result
        total_count = pay_result.get("total", len(data)) if isinstance(pay_result, dict) else len(data)

        total_revenue = sum(float(p.get("cost", 0)) for p in data)
        unique_buyers = len({p.get("customer", "") for p in data if p.get("customer")})
        now = datetime.utcnow()
        month_prefix = f"{now.year}-{now.month:02d}"
        month_data = [p for p in data if str(p.get("created_at", "")).startswith(month_prefix)]
        month_revenue = sum(float(p.get("cost", 0)) for p in month_data)

        overview = {
            "stats": {
                "total_payments": total_count,
                "total_revenue": round(total_revenue, 2),
                "unique_buyers": unique_buyers,
                "month_payments": len(month_data),
                "month_revenue": round(month_revenue, 2),
                "products_count": len(products),
            },
            "payments": pay_result if isinstance(pay_result, dict) else {
                "data": data, "total": total_count, "current_page": 1, "last_page": 1, "per_page": 50,
            },
            "products": products,
            "chart_payments": data,  # all fetched payments for charts
        }
        _cache_set("admin_overview", overview, ttl=300)
        return overview

    def verify_callback_signature(self, payment_id: int, cost: float, customer: str, signature: str) -> bool:
        message = f"{payment_id}@{cost}@{customer}"
        expected = hmac.new(
            self._key.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
