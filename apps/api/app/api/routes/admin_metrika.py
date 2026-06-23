from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.app.config import get_settings
from apps.api.app.dependencies.admin import get_current_admin_user

router = APIRouter(
    prefix="/admin/metrika",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)

_TRAFFIC_SOURCE_NAMES = {
    "organic": "Поиск",
    "direct": "Прямые",
    "referral": "Переходы",
    "social": "Соцсети",
    "ad": "Реклама",
    "email": "Email",
    "internal": "Внутренние",
    "messenger": "Мессенджеры",
    "other": "Прочее",
}

_DEVICE_NAMES = {
    "desktop": "Компьютер",
    "mobile": "Мобильный",
    "tablet": "Планшет",
    "tv": "Smart TV",
}


def _dates(days: int) -> tuple[str, str]:
    now = datetime.now(UTC)
    return (now - timedelta(days=days)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


async def _fetch(client: httpx.AsyncClient, token: str, counter_id: str, params: dict) -> dict:
    resp = await client.get(
        "https://api-metrika.yandex.net/stat/v1/data",
        params={"ids": counter_id, **params},
        headers={"Authorization": f"OAuth {token}"},
    )
    if resp.status_code != 200:
        return {}
    return resp.json()


@router.get("/full")
async def get_full_stats(days: int = Query(default=30, ge=7, le=365)) -> dict:
    settings = get_settings()
    token = settings.yandex_metrika_token
    counter_id = settings.yandex_metrika_counter_id

    if not token or not counter_id:
        raise HTTPException(status_code=503, detail="Yandex Metrika not configured")

    date1, date2 = _dates(days)
    base = {"date1": date1, "date2": date2}

    async with httpx.AsyncClient(timeout=15) as client:
        by_day_task = _fetch(client, token, counter_id, {
            **base,
            "metrics": "ym:s:visits,ym:s:users,ym:s:pageviews",
            "dimensions": "ym:s:date",
            "sort": "ym:s:date",
            "limit": 365,
        })
        sources_task = _fetch(client, token, counter_id, {
            **base,
            "metrics": "ym:s:visits,ym:s:users",
            "dimensions": "ym:s:trafficSource",
            "sort": "-ym:s:visits",
        })
        pages_task = _fetch(client, token, counter_id, {
            **base,
            "metrics": "ym:s:pageviews,ym:s:avgVisitDurationSeconds,ym:s:bounceRate",
            "dimensions": "ym:s:URLPath",
            "sort": "-ym:s:pageviews",
            "limit": 10,
        })
        devices_task = _fetch(client, token, counter_id, {
            **base,
            "metrics": "ym:s:visits",
            "dimensions": "ym:s:deviceCategory",
            "sort": "-ym:s:visits",
        })

        by_day_raw, sources_raw, pages_raw, devices_raw = await asyncio.gather(
            by_day_task, sources_task, pages_task, devices_task
        )

    # --- by day ---
    by_day = []
    for row in by_day_raw.get("data", []):
        dims = row.get("dimensions", [{}])
        metrics = row.get("metrics", [0, 0, 0])
        by_day.append({
            "date": dims[0].get("name", "") if dims else "",
            "visits": int(metrics[0]) if len(metrics) > 0 else 0,
            "users": int(metrics[1]) if len(metrics) > 1 else 0,
            "pageviews": int(metrics[2]) if len(metrics) > 2 else 0,
        })

    # --- totals from by_day ---
    total_visits = sum(d["visits"] for d in by_day)
    total_users = sum(d["users"] for d in by_day)
    total_pageviews = sum(d["pageviews"] for d in by_day)
    totals_raw = by_day_raw.get("totals", [])

    # --- sources ---
    sources = []
    for row in sources_raw.get("data", []):
        dims = row.get("dimensions", [{}])
        metrics = row.get("metrics", [0, 0])
        key = dims[0].get("id", "") if dims else ""
        sources.append({
            "key": key,
            "name": _TRAFFIC_SOURCE_NAMES.get(key, key or "Прочее"),
            "visits": int(metrics[0]) if len(metrics) > 0 else 0,
            "users": int(metrics[1]) if len(metrics) > 1 else 0,
        })

    # --- top pages ---
    pages = []
    for row in pages_raw.get("data", []):
        dims = row.get("dimensions", [{}])
        metrics = row.get("metrics", [0, 0, 0])
        pages.append({
            "path": dims[0].get("name", "/") if dims else "/",
            "pageviews": int(metrics[0]) if len(metrics) > 0 else 0,
            "avg_duration": int(metrics[1]) if len(metrics) > 1 else 0,
            "bounce_rate": round(metrics[2], 1) if len(metrics) > 2 else 0,
        })

    # --- devices ---
    devices = []
    for row in devices_raw.get("data", []):
        dims = row.get("dimensions", [{}])
        metrics = row.get("metrics", [0])
        key = dims[0].get("id", "") if dims else ""
        devices.append({
            "key": key,
            "name": _DEVICE_NAMES.get(key, key or "Прочее"),
            "visits": int(metrics[0]) if len(metrics) > 0 else 0,
        })

    # overall bounce rate from sources totals
    s_totals = sources_raw.get("totals", [0, 0])
    p_totals = pages_raw.get("totals", [0, 0, 0])
    bounce_rate = round(p_totals[2], 1) if len(p_totals) > 2 else 0

    return {
        "period": {"date1": date1, "date2": date2, "days": days},
        "totals": {
            "visits": total_visits,
            "users": total_users,
            "pageviews": total_pageviews,
            "bounce_rate": bounce_rate,
        },
        "by_day": by_day,
        "sources": sources,
        "top_pages": pages,
        "devices": devices,
    }
