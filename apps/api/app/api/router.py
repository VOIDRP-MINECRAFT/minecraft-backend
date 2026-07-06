from __future__ import annotations

from fastapi import APIRouter

from apps.api.app.api.routes.account import router as account_router
from apps.api.app.api.routes.admin import router as admin_router
from apps.api.app.api.routes.admin_dashboard import router as admin_dashboard_router
from apps.api.app.api.routes.admin_market import router as admin_market_router
from apps.api.app.api.routes.admin_metrika import router as admin_metrika_router
from apps.api.app.api.routes.auth import router as auth_router
from apps.api.app.api.routes.game_sync import router as game_sync_router
from apps.api.app.api.routes.economy_market import router as economy_market_router
from apps.api.app.api.routes.market_public import router as market_public_router
from apps.api.app.api.routes.health import router as health_router
from apps.api.app.api.routes.launcher_dashboard import router as launcher_dashboard_router
from apps.api.app.api.routes.launcher_prefs import router as launcher_prefs_router
from apps.api.app.api.routes.nations import router as nations_router
from apps.api.app.api.routes.nation_stats import router as nation_stats_router
from apps.api.app.api.routes.play_ticket import launcher_router as launcher_router
from apps.api.app.api.routes.play_ticket import server_router as server_auth_ticket_router
from apps.api.app.api.routes.profiles import router as profiles_router
from apps.api.app.api.routes.referrals import router as referrals_router
from apps.api.app.api.routes.server_auth import router as server_auth_router
from apps.api.app.api.routes.social import router as social_router
from apps.api.app.api.routes.alliances import router as alliances_router
from apps.api.app.api.routes.donate import router as donate_router
from apps.api.app.api.routes.mod_suggestions import router as mod_suggestions_router
from apps.api.app.api.routes.player_stats import router as player_stats_router
from apps.api.app.api.routes.progression import router as progression_router
from apps.api.app.api.routes.battlepass import router as battlepass_router
from apps.api.app.api.routes.admin_battlepass import router as admin_battlepass_router
from apps.api.app.api.routes.admin_donate import router as admin_donate_router
from apps.api.app.api.routes.admin_anticheat import router as admin_anticheat_router
from apps.api.app.api.routes.game_sync_anticheat import router as game_sync_anticheat_router
from apps.api.app.api.routes.launcher_crash import router as launcher_crash_router
from apps.api.app.api.routes.admin_launcher_crashes import router as admin_launcher_crashes_router
from apps.api.app.api.routes.game_sync_alliances import router as game_sync_alliances_router
from apps.api.app.api.routes.admin_landing import router as admin_landing_router
from apps.api.app.api.routes.landing import router as landing_router
from apps.api.app.api.routes.player_heads import router as player_heads_router
from apps.api.app.api.routes.player_feedback import router as player_feedback_router
from apps.api.app.api.routes.player_market import (
    router_game_sync as player_market_game_sync_router,
    router_public as player_market_public_router,
    router_player as player_market_player_router,
)
from apps.api.app.api.routes.game_ui_market import router as game_ui_market_router
from apps.api.app.api.routes.game_ui_market import router_plugin as game_ui_market_plugin_router
from apps.api.app.api.routes.game_ui_hud import router as game_ui_hud_router
from apps.api.app.api.routes.game_ui_nation_market import router as game_ui_nation_market_router
from apps.api.app.api.routes.game_ui_treasury import router as game_ui_treasury_router
from apps.api.app.api.routes.game_ui_battlepass import router as game_ui_battlepass_router
from apps.api.app.api.routes.game_ui_alliance import router as game_ui_alliance_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(account_router)
api_router.include_router(launcher_dashboard_router)
api_router.include_router(launcher_prefs_router)
api_router.include_router(launcher_router)
api_router.include_router(server_auth_ticket_router)
api_router.include_router(server_auth_router)
api_router.include_router(admin_router)
api_router.include_router(admin_dashboard_router)
api_router.include_router(admin_market_router)
api_router.include_router(admin_metrika_router)
api_router.include_router(profiles_router)
api_router.include_router(social_router)
api_router.include_router(referrals_router)
api_router.include_router(nations_router)
api_router.include_router(nation_stats_router)
api_router.include_router(game_sync_router)
api_router.include_router(economy_market_router)
api_router.include_router(market_public_router)
api_router.include_router(alliances_router)
api_router.include_router(progression_router)
api_router.include_router(player_stats_router)
api_router.include_router(donate_router)
api_router.include_router(mod_suggestions_router)
api_router.include_router(battlepass_router)
api_router.include_router(admin_battlepass_router)
api_router.include_router(admin_donate_router)
api_router.include_router(admin_anticheat_router)
api_router.include_router(game_sync_anticheat_router)
api_router.include_router(launcher_crash_router)
api_router.include_router(admin_launcher_crashes_router)
api_router.include_router(game_sync_alliances_router)
api_router.include_router(admin_landing_router)
api_router.include_router(landing_router)
api_router.include_router(player_heads_router)
api_router.include_router(player_feedback_router)
api_router.include_router(player_market_game_sync_router)
api_router.include_router(player_market_public_router)
api_router.include_router(player_market_player_router)
api_router.include_router(game_ui_market_router)
api_router.include_router(game_ui_market_plugin_router)
api_router.include_router(game_ui_hud_router)
api_router.include_router(game_ui_nation_market_router)
api_router.include_router(game_ui_treasury_router)
api_router.include_router(game_ui_battlepass_router)
api_router.include_router(game_ui_alliance_router)
