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
from apps.api.app.api.routes.servers import router as servers_router
from apps.api.app.api.routes.admin_servers import router as admin_servers_router
from apps.api.app.api.routes.admin_server_ops import router as admin_server_ops_router
from apps.api.app.api.routes.admin_audit import router as admin_audit_router
from apps.api.app.api.routes.admin_punishments import router as admin_punishments_router
from apps.api.app.api.routes.admin_player_overview import router as admin_player_overview_router
from apps.api.app.api.routes.monitoring_prometheus import router as monitoring_prometheus_router
from apps.api.app.api.routes.admin_mods import router as admin_mods_router
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
from apps.api.app.api.routes.game_sync_claims import router as game_sync_claims_router
from apps.api.app.api.routes.claims import router as claims_router
from apps.api.app.api.routes.game_sync_bounties import router as game_sync_bounties_router
from apps.api.app.api.routes.bounties import router as bounties_router
from apps.api.app.api.routes.game_sync_tiktok import router as game_sync_tiktok_router
from apps.api.app.api.routes.tiktok_public import router as tiktok_public_router
from apps.api.app.api.routes.news import router as news_router
from apps.api.app.api.routes.admin_news import router as admin_news_router
from apps.api.app.api.routes.admin_moderators import router as admin_moderators_router
from apps.api.app.api.routes.admin_notifications import router as admin_notifications_router
from apps.api.app.api.routes.profile_telegram import router as profile_telegram_router
from apps.api.app.api.routes.game_sync_stats import router as game_sync_stats_router
from apps.api.app.api.routes.game_sync_killfeed import router as game_sync_killfeed_router
from apps.api.app.api.routes.killfeed import router as killfeed_router
from apps.api.app.api.routes.launcher_crash import router as launcher_crash_router
from apps.api.app.api.routes.admin_launcher_crashes import router as admin_launcher_crashes_router
from apps.api.app.api.routes.admin_launcher import router as admin_launcher_router
from apps.api.app.api.routes.game_sync_alliances import router as game_sync_alliances_router
from apps.api.app.api.routes.game_sync_void_coins import router as game_sync_void_coins_router
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
from apps.api.app.api.routes.game_ui_upgrader import router as game_ui_upgrader_router
from apps.api.app.api.routes.game_ui_cosmetics import router as game_ui_cosmetics_router
from apps.api.app.api.routes.game_ui_cosmetics import plugin_router as game_ui_cosmetics_plugin_router
from apps.api.app.api.routes.admin_upgrader import router as admin_upgrader_router
from apps.api.app.api.routes.admin_cosmetics import router as admin_cosmetics_router
from apps.api.app.api.routes.game_ui_nation_market import router as game_ui_nation_market_router
from apps.api.app.api.routes.game_ui_treasury import router as game_ui_treasury_router
from apps.api.app.api.routes.game_ui_research import router as game_ui_research_router
from apps.api.app.api.routes.game_ui_research import plugin_router as nation_research_plugin_router
from apps.api.app.api.routes.game_ui_notifications import router as game_ui_notifications_router
from apps.api.app.api.routes.game_ui_notifications import plugin_router as notifications_plugin_router
from apps.api.app.api.routes.game_ui_activity import router as game_ui_activity_router
from apps.api.app.api.routes.game_ui_activity import plugin_router as activity_plugin_router
from apps.api.app.api.routes.game_ui_weekly import router as game_ui_weekly_router
from apps.api.app.api.routes.game_ui_weekly import plugin_router as weekly_plugin_router
from apps.api.app.api.routes.game_ui_settings import router as game_ui_settings_router
from apps.api.app.api.routes.game_ui_settings import plugin_router as player_settings_plugin_router
from apps.api.app.api.routes.game_ui_leaderboards import router as game_ui_leaderboards_router
from apps.api.app.api.routes.game_sync_season import plugin_router as season_plugin_router
from apps.api.app.api.routes.game_ui_quests import router as game_ui_quests_router
from apps.api.app.api.routes.game_ui_quests import plugin_router as game_ui_quests_plugin_router
from apps.api.app.api.routes.game_ui_home import router as game_ui_home_router
from apps.api.app.api.routes.game_ui_battlepass import router as game_ui_battlepass_router
from apps.api.app.api.routes.game_ui_battlepass import plugin_router as game_ui_battlepass_plugin_router
from apps.api.app.api.routes.game_ui_alliance import router as game_ui_alliance_router
from apps.api.app.api.routes.voxel import router as voxel_router
from apps.api.app.api.routes.admin_voxel import router as admin_voxel_router
from apps.api.app.api.routes.game_ui_voxel import router as game_ui_voxel_router

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
api_router.include_router(game_sync_void_coins_router)
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
api_router.include_router(game_sync_claims_router)
api_router.include_router(claims_router)
api_router.include_router(game_sync_bounties_router)
api_router.include_router(bounties_router)
api_router.include_router(game_sync_tiktok_router)
api_router.include_router(tiktok_public_router)
api_router.include_router(news_router)
api_router.include_router(admin_news_router)
api_router.include_router(admin_moderators_router)
api_router.include_router(admin_notifications_router)
api_router.include_router(profile_telegram_router)
api_router.include_router(game_sync_stats_router)
api_router.include_router(game_sync_killfeed_router)
api_router.include_router(killfeed_router)
api_router.include_router(launcher_crash_router)
api_router.include_router(admin_launcher_crashes_router)
api_router.include_router(admin_launcher_router)
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
api_router.include_router(game_ui_upgrader_router)
api_router.include_router(game_ui_cosmetics_router)
api_router.include_router(game_ui_cosmetics_plugin_router)
api_router.include_router(admin_upgrader_router)
api_router.include_router(admin_cosmetics_router)
api_router.include_router(game_ui_nation_market_router)
api_router.include_router(game_ui_treasury_router)
api_router.include_router(game_ui_research_router)
api_router.include_router(nation_research_plugin_router)
api_router.include_router(game_ui_notifications_router)
api_router.include_router(game_ui_activity_router)
api_router.include_router(activity_plugin_router)
api_router.include_router(game_ui_weekly_router)
api_router.include_router(weekly_plugin_router)
api_router.include_router(game_ui_settings_router)
api_router.include_router(player_settings_plugin_router)
api_router.include_router(notifications_plugin_router)
api_router.include_router(game_ui_leaderboards_router)
api_router.include_router(season_plugin_router)
api_router.include_router(game_ui_quests_router)
api_router.include_router(game_ui_quests_plugin_router)
api_router.include_router(game_ui_home_router)
api_router.include_router(game_ui_battlepass_router)
api_router.include_router(game_ui_battlepass_plugin_router)
api_router.include_router(game_ui_alliance_router)
api_router.include_router(servers_router)
api_router.include_router(admin_servers_router)
api_router.include_router(admin_server_ops_router)
api_router.include_router(admin_audit_router)
api_router.include_router(admin_punishments_router)
api_router.include_router(admin_player_overview_router)
api_router.include_router(monitoring_prometheus_router)
api_router.include_router(admin_mods_router)
api_router.include_router(voxel_router)
api_router.include_router(admin_voxel_router)
api_router.include_router(game_ui_voxel_router)
