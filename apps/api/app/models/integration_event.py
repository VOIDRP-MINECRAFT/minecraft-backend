"""What happened to a server's VoidRP plugins — the «Интеграция» page's history."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base


class IntegrationEvent(Base):
    __tablename__ = "server_integration_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # module_on | module_off | version | plugin_new | quiet | back | secret
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    plugin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
