from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from apps.api.app.config import get_settings
from apps.api.app.models.base import Base
from apps.api.app.models.alliance import Alliance, AllianceMember, AllianceProposal, AllianceVote
from apps.api.app.models.email_token import EmailToken
from apps.api.app.models.media_asset import MediaAsset
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_activity_log import NationActivityLog
from apps.api.app.models.nation_join_request import NationJoinRequest
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_member_stat_snapshot import NationMemberStatSnapshot
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_follow import PlayerFollow
from apps.api.app.models.player_public_profile import PlayerPublicProfile
from apps.api.app.models.play_ticket import PlayTicket
from apps.api.app.models.referral_code import ReferralCode
from apps.api.app.models.referral_link import ReferralLink
from apps.api.app.models.referral_reward_period import ReferralRewardPeriod
from apps.api.app.models.refresh_session import RefreshSession
from apps.api.app.models.user import User

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
