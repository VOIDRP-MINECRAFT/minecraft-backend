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


class Achievement(BaseModel):
    key: str
    title: str
    desc: str
    icon: str
    unlocked: bool
    progress: int
    goal: int


# Derived from existing counters — no separate award table, always recomputed.
# (title, desc, icon, goal, metric-key). metric-key indexes into the values dict below.
_ACHIEVEMENTS: list[tuple[str, str, str, str, int, str]] = [
    ("citizen", "Гражданин", "Вступи в государство", "users", 1, "in_nation"),
    ("first_blood", "Первая кровь", "Убей игрока", "shield", 1, "pvp_kills"),
    ("warrior", "Воин", "25 убийств игроков", "shield", 25, "pvp_kills"),
    ("streak5", "На волне", "Серия из 5 убийств", "crown", 5, "best_kill_streak"),
    ("streak10", "Неудержимый", "Серия из 10 убийств", "crown", 10, "best_kill_streak"),
    ("hunter", "Охотник", "Убей 100 мобов", "quest", 100, "mob_kills"),
    ("slayer", "Истребитель", "Убей 500 мобов", "quest", 500, "mob_kills"),
    ("miner", "Шахтёр", "Добудь 1000 блоков", "tech", 1000, "blocks_broken"),
    ("builder", "Строитель", "Поставь 1000 блоков", "tech", 1000, "blocks_placed"),
    ("veteran", "Ветеран", "10 часов в игре", "trophy", 600, "playtime_minutes"),
    ("quester", "Квестор", "Заверши 25 квестов", "quest", 25, "completed_quests"),
    ("tycoon", "Магнат", "Накопи 100 000 монет", "coins", 100000, "balance"),
]


def _compute_achievements(stats: "HomeStats", has_nation: bool) -> list[Achievement]:
    values = {
        "in_nation": 1 if has_nation else 0,
        "pvp_kills": stats.pvp_kills,
        "best_kill_streak": stats.best_kill_streak,
        "mob_kills": stats.mob_kills,
        "blocks_broken": stats.blocks_broken,
        "blocks_placed": stats.blocks_placed,
        "playtime_minutes": stats.playtime_minutes,
        "completed_quests": stats.completed_quests,
        "balance": int(stats.balance),
    }
    out: list[Achievement] = []
    for key, title, desc, icon, goal, metric in _ACHIEVEMENTS:
        cur = int(values.get(metric, 0))
        out.append(Achievement(
            key=key, title=title, desc=desc, icon=icon, goal=goal,
            progress=min(cur, goal), unlocked=cur >= goal,
        ))
    # Unlocked first, then closest-to-done, so the card leads with earned/near badges.
    out.sort(key=lambda a: (not a.unlocked, -(a.progress / a.goal if a.goal else 0)))
    return out


class OnboardingStep(BaseModel):
    key: str
    label: str
    hint: str
    done: bool


def _compute_onboarding(stats: "HomeStats", has_nation: bool, bp_level: int) -> list[OnboardingStep]:
    """First-session checklist for new players; drops off as steps complete."""
    steps = [
        ("nation", "Вступи в государство", "Открой вкладку «Нации» на сайте или /nation", has_nation),
        ("play", "Наиграй 30 минут", "Просто играй — прогресс идёт сам", stats.playtime_minutes >= 30),
        ("blocks", "Поставь или сломай блок", "Начни осваиваться в мире", (stats.blocks_placed + stats.blocks_broken) > 0),
        ("quest", "Выполни первый квест", "Загляни во вкладку «Квесты» (F6)", stats.completed_quests >= 1),
        ("earn", "Заработай монеты", "Продавай ресурсы на рынке", stats.balance > 1000),
        ("level", "Достигни 5 уровня пропуска", "Активность даёт опыт баттлпасса", bp_level >= 5),
    ]
    return [OnboardingStep(key=k, label=l, hint=h, done=d) for k, l, h, d in steps]


class HomeProfile(BaseModel):
    nickname: str
    skin_url: str
    skin_slim: bool
    registered_at: datetime | None
    nation: HomeNation | None
    battlepass: HomeBattlePass | None
    stats: HomeStats
    achievements: list[Achievement] = []
    onboarding: list[OnboardingStep] = []


class TopBar(BaseModel):
    nickname: str
    skin_url: str
    balance: float = 0
    void_coins: int = 0
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
        nickname=nick, skin_url=skin_url, balance=balance, void_coins=int(player.void_coins or 0),
        level=bp.level if bp else 0, nation_tag=tag, accent_color=accent,
    )


class NationEvent(BaseModel):
    event_type: str
    message: str | None
    actor: str | None
    created_at: datetime


@router.get("/nation-activity", response_model=list[NationEvent])
def get_nation_activity(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    limit: int = 12,
) -> list[NationEvent]:
    """Recent activity of the player's own nation, for the home feed."""
    member = db.execute(
        select(NationMember).where(
            NationMember.user_id == player.user_id, NationMember.server_id == server.id
        )
    ).scalar_one_or_none()
    if member is None:
        return []
    from apps.api.app.models.nation_activity_log import NationActivityLog
    from apps.api.app.models.user import User

    rows = db.execute(
        select(NationActivityLog, PlayerAccount.minecraft_nickname)
        .outerjoin(User, User.id == NationActivityLog.actor_user_id)
        .outerjoin(PlayerAccount, PlayerAccount.user_id == User.id)
        .where(
            NationActivityLog.nation_id == member.nation_id,
            NationActivityLog.server_id == server.id,
        )
        .order_by(NationActivityLog.created_at.desc())
        .limit(max(1, min(limit, 30)))
    ).all()
    return [
        NationEvent(
            event_type=log.event_type,
            message=log.message,
            actor=nick,
            created_at=log.created_at,
        )
        for log, nick in rows
    ]


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
        achievements=_compute_achievements(stats, nation_out is not None),
        onboarding=_compute_onboarding(stats, nation_out is not None, bp_out.level if bp_out else 0),
    )
