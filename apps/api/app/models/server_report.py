"""What our plugins on a game server report about themselves (docs/external_servers_plan.md).

Every VoidRP plugin posts a heartbeat: its version, the server core, which modules run and,
for the monitoring module, live numbers (TPS, players, memory, uptime). The admin panel
reads it for the «Интеграция» checklist, for the required modules of an external server
(login and monitoring) and for monitoring without RCON.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base


class ServerPluginReport(Base):
    __tablename__ = "server_plugin_reports"

    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True)
    # "VoidRpAuth", "VoidRpPerms", …
    plugin: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "Paper 26.2-124-ver/26.2@22ca6c7" — whatever Bukkit.getName()/getVersion() say
    core: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # {"auth": {"ok": true, "detail": "…"}, "monitoring": {"ok": true}, …}
    modules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Live numbers of the monitoring module; {} for other plugins.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
