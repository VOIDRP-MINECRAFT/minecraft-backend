from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from apps.api.app.models.alliance import Alliance
    from apps.api.app.models.nation import Nation
    from apps.api.app.models.user import User


class NationTreasuryTransaction(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "nation_treasury_transactions"

    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)

    nation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("nations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    counterparty_nation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("nations.id", ondelete="SET NULL"),
        nullable=True,
    )
    alliance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("alliances.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    gross_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    fee_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    nation: Mapped["Nation | None"] = relationship(
        "Nation",
        foreign_keys=[nation_id],
    )
    counterparty_nation: Mapped["Nation | None"] = relationship(
        "Nation",
        foreign_keys=[counterparty_nation_id],
    )
    alliance: Mapped["Alliance | None"] = relationship("Alliance")
    created_by_user: Mapped["User | None"] = relationship("User")