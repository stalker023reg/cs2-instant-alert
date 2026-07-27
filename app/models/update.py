"""
CS2 Instant Alert — Update Model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class Update(UUIDMixin, Base):
    """
    Detected game update record.

    Stores full details about a detected update including BuildID,
    depot/manifest changes, size, and patch notes (when available).
    """

    __tablename__ = "updates"

    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    build_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    previous_build_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Patch notes
    patch_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    patch_notes_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    patch_notes_fetched: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Raw change data
    depot_changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    manifest_changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timeline
    timeline: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=lambda: {"events": []})

    # Timestamps
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ─── Relationships ───
    game = relationship("Game", back_populates="updates")
    notification_history = relationship(
        "NotificationHistory", back_populates="update", lazy="noload"
    )
    alert_acknowledgements = relationship(
        "AlertAcknowledgement", back_populates="update", lazy="noload"
    )

    def __repr__(self) -> str:
        return (
            f"<Update(game_id={self.game_id}, build_id={self.build_id}, "
            f"detected_at={self.detected_at})>"
        )
