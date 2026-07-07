from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.dependencies.admin import get_current_admin_user
from apps.api.app.models.alliance import Alliance
from apps.api.app.models.battlepass import BattlePassPremium, BattlePassProgress
from apps.api.app.models.economy_market import EconomyMarketItem, EconomyShopTransaction
from apps.api.app.models.mod_suggestion import ModSuggestion
from apps.api.app.models.nation import Nation
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/dashboard",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)


def _get_admin_db_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> Session:
    return session


@router.get("/stats")
def get_dashboard_stats(
    session: Annotated[Session, Depends(_get_admin_db_service)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_users = session.scalar(select(func.count()).select_from(User)) or 0
    active_users = session.scalar(select(func.count()).select_from(User).where(User.is_active)) or 0
    verified_users = (
        session.scalar(select(func.count()).select_from(User).where(User.email_verified)) or 0
    )
    new_week = (
        session.scalar(
            select(func.count()).select_from(User).where(User.created_at >= week_ago)
        )
        or 0
    )
    new_month = (
        session.scalar(
            select(func.count()).select_from(User).where(User.created_at >= month_ago)
        )
        or 0
    )
    total_players = session.scalar(select(func.count()).select_from(PlayerAccount)) or 0
    total_nations = session.scalar(select(func.count()).select_from(Nation).where(Nation.server_id == server.id)) or 0
    total_alliances = session.scalar(select(func.count()).select_from(Alliance).where(Alliance.server_id == server.id)) or 0
    total_mod_suggestions = session.scalar(select(func.count()).select_from(ModSuggestion)) or 0

    # Battle Pass
    bp_total = session.scalar(select(func.count()).select_from(BattlePassPremium).where(BattlePassPremium.server_id == server.id)) or 0
    bp_active = session.scalar(
        select(func.count())
        .select_from(BattlePassPremium)
        .where(BattlePassPremium.server_id == server.id, BattlePassPremium.expires_at > now)
    ) or 0
    bp_progress_count = session.scalar(select(func.count()).select_from(BattlePassProgress).where(BattlePassProgress.server_id == server.id)) or 0

    # Market
    market_items = session.scalar(select(func.count()).select_from(EconomyMarketItem).where(EconomyMarketItem.server_id == server.id)) or 0
    market_enabled = session.scalar(
        select(func.count())
        .select_from(EconomyMarketItem)
        .where(EconomyMarketItem.server_id == server.id, EconomyMarketItem.enabled)
    ) or 0
    market_tx_week = session.scalar(
        select(func.count()).select_from(EconomyShopTransaction).where(
            EconomyShopTransaction.server_id == server.id,
            EconomyShopTransaction.created_at >= week_ago,
        )
    ) or 0

    # Registrations trend: daily new users for last 14 days
    trend_start = now - timedelta(days=13)
    _day = func.date_trunc(literal_column("'day'"), User.created_at)
    trend_rows = session.execute(
        select(
            _day.label("day"),
            func.count().label("cnt"),
        )
        .where(User.created_at >= trend_start)
        .group_by(_day)
        .order_by(_day)
    ).all()
    # Fill all 14 days (including zeros)
    from collections import defaultdict
    trend_map: dict[str, int] = defaultdict(int)
    for row in trend_rows:
        trend_map[row.day.strftime("%Y-%m-%d")] = int(row.cnt)
    reg_trend = []
    for i in range(14):
        d = (trend_start + timedelta(days=i)).strftime("%Y-%m-%d")
        reg_trend.append({"date": d, "count": trend_map[d]})

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "verified": verified_users,
            "new_last_7d": new_week,
            "new_last_30d": new_month,
            "reg_trend": reg_trend,
        },
        "players": {
            "total": total_players,
        },
        "nations": {
            "total": total_nations,
        },
        "alliances": {
            "total": total_alliances,
        },
        "mod_suggestions": {
            "total": total_mod_suggestions,
        },
        "battlepass": {
            "active_premium": bp_active,
            "total_premium": bp_total,
            "progress_count": bp_progress_count,
        },
        "market": {
            "total_items": market_items,
            "enabled_items": market_enabled,
            "tx_last_7d": market_tx_week,
        },
    }


@router.get("/server-status")
def get_server_status() -> dict:
    settings = get_settings()
    host = settings.minecraft_server_host
    port = settings.minecraft_server_port

    if not host:
        return {"online": False, "reason": "server host not configured"}

    try:
        from mcstatus import JavaServer  # type: ignore[import-untyped]

        server = JavaServer(host, port, timeout=3)
        status = server.status()
        return {
            "online": True,
            "players_online": status.players.online,
            "players_max": status.players.max,
            "version": status.version.name,
            "latency_ms": round(status.latency, 1),
            "players_sample": [
                {"name": p.name, "id": str(p.id)}
                for p in (status.players.sample or [])
            ],
        }
    except ImportError:
        return {"online": False, "reason": "mcstatus not installed"}
    except Exception as exc:
        return {"online": False, "reason": str(exc)}


@router.get("/recent-users")
def get_recent_users(
    session: Annotated[Session, Depends(_get_admin_db_service)],
) -> dict:
    rows = (
        session.execute(
            select(User, PlayerAccount)
            .outerjoin(PlayerAccount, PlayerAccount.user_id == User.id)
            .order_by(User.created_at.desc())
            .limit(20)
        )
        .all()
    )

    users = []
    for user, pa in rows:
        users.append(
            {
                "id": str(user.id),
                "site_login": user.site_login,
                "email": user.email,
                "email_verified": user.email_verified,
                "is_active": user.is_active,
                "is_admin": user.is_admin,
                "created_at": user.created_at.isoformat(),
                "minecraft_nickname": pa.minecraft_nickname if pa else None,
            }
        )

    return {"users": users}


@router.get("/metrika")
async def get_metrika_stats() -> dict:
    settings = get_settings()
    token = settings.yandex_metrika_token
    counter_id = settings.yandex_metrika_counter_id

    if not token or not counter_id:
        raise HTTPException(status_code=503, detail="Yandex Metrika not configured")

    now = datetime.now(UTC)
    date2 = now.strftime("%Y-%m-%d")
    date1 = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api-metrika.yandex.net/stat/v1/data",
            params={
                "ids": counter_id,
                "metrics": "ym:s:visits,ym:s:users,ym:s:pageviews,ym:s:bounceRate",
                "date1": date1,
                "date2": date2,
            },
            headers={"Authorization": f"OAuth {token}"},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Metrika API error")

    data = resp.json()
    totals = data.get("totals", [0, 0, 0, 0])

    return {
        "visits": int(totals[0]) if len(totals) > 0 else 0,
        "users": int(totals[1]) if len(totals) > 1 else 0,
        "pageviews": int(totals[2]) if len(totals) > 2 else 0,
        "bounce_rate": round(totals[3], 1) if len(totals) > 3 else 0,
        "date1": date1,
        "date2": date2,
    }
