"""Console queue and shipped log lines of a server whose plugin talks to the backend itself."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base


class ServerCommand(Base):
    __tablename__ = "server_commands"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", server_default="pending")
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ServerLogLine(Base):
    __tablename__ = "server_log_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False)
    line: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
