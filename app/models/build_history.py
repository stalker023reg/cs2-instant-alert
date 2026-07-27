"""
CS2 Instant Alert — Build History Model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class BuildHistory(UUIDMixin, Base):
    """
    Historical record of observed BuildIDs for a game.

    Tracks every unique BuildID per branch, with manifest snapshots
    and change numbers for forensic analysis.
    """

    __tablename__ = "build_history"

    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    build_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(
        String(50), default="public", nullable=False
    )
    change_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    manifests: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ─── Relationships ───
    game = relationship("Game", back_populates="build_history")

    def __repr__(self) -> str:
        return (
            f"<BuildHistory(game_id={self.game_id}, build_id={self.build_id}, "
            f"branch={self.branch})>"
        )
