"""
CS2 Instant Alert — Steam App State Model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class SteamAppState(UUIDMixin, Base):
    """
    Persisted monitoring state for a Steam game.

    Stores the last known BuildID, change number, manifests,
    and Race Mode status. Survives application restarts.
    """

    __tablename__ = "steam_app_state"

    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    last_build_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_change_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_manifests: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_depot_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    last_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_update_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Race Mode state
    race_mode_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    race_mode_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ─── Relationships ───
    game = relationship("Game", back_populates="state")

    def __repr__(self) -> str:
        return (
            f"<SteamAppState(game_id={self.game_id}, "
            f"build_id={self.last_build_id}, race_mode={self.race_mode_active})>"
        )
