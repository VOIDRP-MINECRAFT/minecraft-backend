from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

# whitelist_mode values
WHITELIST_MODE_PUBLIC = "public"
WHITELIST_MODE_WHITELIST = "whitelist"
WHITELIST_MODE_INVITE = "invite"


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

    # ── Status / policy ───────────────────────────────────────────────────
    status_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_players: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    whitelist_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WHITELIST_MODE_PUBLIC
    )
    maintenance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Game-server auth ──────────────────────────────────────────────────
    game_auth_secret: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
