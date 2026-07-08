from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

# whitelist_mode values
WHITELIST_MODE_PUBLIC = "public"
WHITELIST_MODE_WHITELIST = "whitelist"
WHITELIST_MODE_INVITE = "invite"

# Per-server feature flags. Absent/unknown keys default to enabled, so the
# default server keeps every tab. Admin toggles these to hide sections on
# servers that don't have that game system (e.g. a vanilla server has no
# nations/economy). Consumed by the launcher nav and the site nav.
SERVER_FEATURE_KEYS = (
    "nations",
    "economy",
    "shop",
    "alliances",
    "battlepass",
    "quests",
    "leaderboards",
    "map",
)


def default_features() -> dict[str, bool]:
    return {key: True for key in SERVER_FEATURE_KEYS}


class GameServer(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A single Minecraft server instance the launcher can connect to.

    The account layer (users / player_accounts) is global, but game data
    (nations, economy, stats, tickets ...) is scoped per server via ``server_id``.
    """

    __tablename__ = "game_servers"

    # ── Identity / showcase ────────────────────────────────────────────────
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    banner_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # ── Connection / runtime ──────────────────────────────────────────────
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=25565)
    mc_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.21.1")
    loader: Mapped[str] = mapped_column(String(32), nullable=False, default="neoforge")
    java_version: Mapped[int] = mapped_column(Integer, nullable=False, default=21)
    neoforge_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Modpack / launcher manifest ───────────────────────────────────────
    pack_root: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pack_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    manifest_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pack_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    min_launcher_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    # Java-runtime bootstrap for this server's pack. Seed = small JSON that
    # points to the platform manifest; manifest URL is the direct fallback
    # (or a base URL — the launcher appends the platform file name if the
    # value doesn't end with .json). Null → launcher-global defaults.
    runtime_seed_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    runtime_manifest_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Status / policy ───────────────────────────────────────────────────
    status_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_players: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    whitelist_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WHITELIST_MODE_PUBLIC
    )
    maintenance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Features / integrations ───────────────────────────────────────────
    # Web map (Bluemap/Dynmap) URL for this server; empty hides/disables the map tab.
    map_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Theme accent (hex, e.g. #7c3aed) used by the site/launcher to tint the UI
    # for this server. Null → the default VoidRP violet.
    accent_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # EasyDonate server id this game server maps to. Products/commands for a
    # purchase are delivered to this EasyDonate server. Null → use the global default.
    easydonate_server_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Feature flags controlling which tabs/sections appear in launcher & site.
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=default_features)

    # ── Game-server auth ──────────────────────────────────────────────────
    game_auth_secret: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
