"""Home / profile dashboard for the in-game WebGUI (F6 main page)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_skin import PlayerSkin
from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.services.battlepass_service import BattlePassService

router = APIRouter(prefix="/game-ui/home", tags=["game-ui", "home"])


class HomeNation(BaseModel):
    slug: str
    title: str
    tag: str
    accent_color: str | None
    role: str
    custom_prefix: str | None


class HomeBattlePass(BaseModel):
    level: int
    xp: int
    has_premium: bool
    season: str | None


class HomeStats(BaseModel):
    playtime_minutes: int = 0
    balance: float = 0
    pvp_kills: int = 0
    mob_kills: int = 0
    deaths: int = 0
    best_kill_streak: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0
    completed_quests: int = 0
    last_seen_at: datetime | None = None


class HomeProfile(BaseModel):
    nickname: str
    skin_url: str
    skin_slim: bool
    registered_at: datetime | None
    nation: HomeNation | None
    battlepass: HomeBattlePass | None
    stats: HomeStats


class TopBar(BaseModel):
    nickname: str
    skin_url: str
    balance: float = 0
    level: int = 0
    nation_tag: str | None = None
    accent_color: str | None = None


@router.get("/topbar", response_model=TopBar)
def get_topbar(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> TopBar:
    nick = player.minecraft_nickname
    skin = db.execute(select(PlayerSkin).where(PlayerSkin.user_id == player.user_id)).scalar_one_or_none()
    skin_url = skin.original_url if skin and skin.original_url else f"https://mc-heads.net/skin/{nick}"

    stat = db.execute(
        select(PlayerStatCache).where(
            PlayerStatCache.server_id == server.id,
            PlayerStatCache.minecraft_nickname_normalized == nick.lower(),
        )
    ).scalar_one_or_none()
    balance = float(stat.current_balance or 0) if stat else 0

    tag = None
    accent = None
    member = db.execute(
        select(NationMember).where(NationMember.user_id == player.user_id, NationMember.server_id == server.id)
    ).scalar_one_or_none()
    if member is not None:
        nation = db.execute(select(Nation).where(Nation.id == member.nation_id)).scalar_one_or_none()
        if nation is not None:
            tag = nation.tag
            accent = nation.accent_color

    bp = BattlePassService(session=db, server_id=server.id).get_public_profile_by_nick(nick)
    return TopBar(
        nickname=nick, skin_url=skin_url, balance=balance,
        level=bp.level if bp else 0, nation_tag=tag, accent_color=accent,
    )


@router.get("", response_model=HomeProfile)
def get_home(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> HomeProfile:
    nick = player.minecraft_nickname

    # Skin (custom offline skin if uploaded, else Minecraft-head fallback)
    skin = db.execute(
        select(PlayerSkin).where(PlayerSkin.user_id == player.user_id)
    ).scalar_one_or_none()
    skin_url = skin.original_url if skin and skin.original_url else f"https://mc-heads.net/skin/{nick}"
    skin_slim = bool(skin and skin.model_variant == "slim")

    # Nation membership
    nation_out: HomeNation | None = None
    member = db.execute(
        select(NationMember).where(
            NationMember.user_id == player.user_id, NationMember.server_id == server.id
        )
    ).scalar_one_or_none()
    if member is not None:
        nation = db.execute(
            select(Nation).where(Nation.id == member.nation_id)
        ).scalar_one_or_none()
        if nation is not None:
            nation_out = HomeNation(
                slug=nation.slug,
                title=nation.title,
                tag=nation.tag,
                accent_color=nation.accent_color,
                role=member.role,
                custom_prefix=member.custom_prefix,
            )

    # Battle pass
    bp_out: HomeBattlePass | None = None
    bp = BattlePassService(session=db, server_id=server.id).get_public_profile_by_nick(nick)
    if bp is not None:
        bp_out = HomeBattlePass(
            level=bp.level, xp=bp.xp, has_premium=bp.has_premium, season=bp.season
        )

    # Stats
    stat = db.execute(
        select(PlayerStatCache).where(
            PlayerStatCache.server_id == server.id,
            PlayerStatCache.minecraft_nickname_normalized == nick.lower(),
        )
    ).scalar_one_or_none()
    stats = HomeStats()
    if stat is not None:
        stats = HomeStats(
            playtime_minutes=stat.total_playtime_minutes,
            balance=float(stat.current_balance or 0),
            pvp_kills=stat.pvp_kills,
            mob_kills=stat.mob_kills,
            deaths=stat.deaths,
            best_kill_streak=stat.best_kill_streak,
            blocks_placed=stat.blocks_placed,
            blocks_broken=stat.blocks_broken,
            completed_quests=stat.completed_quests,
            last_seen_at=stat.last_seen_at,
        )

    return HomeProfile(
        nickname=nick,
        skin_url=skin_url,
        skin_slim=skin_slim,
        registered_at=getattr(player, "created_at", None),
        nation=nation_out,
        battlepass=bp_out,
        stats=stats,
    )
