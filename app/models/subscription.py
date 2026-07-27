"""
CS2 Instant Alert — Subscription Model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Subscription(UUIDMixin, TimestampMixin, Base):
    """
    User subscription to a specific game's updates.

    Controls per-game notification preferences:
    critical alerts, repeat behavior, intervals.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "game_id", name="uq_subscription_user_game"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    critical_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    repeat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    repeat_interval_seconds: Mapped[int] = mapped_column(
        Integer, default=120, nullable=False
    )

    # ─── Relationships ───
    user = relationship("User", back_populates="subscriptions")
    game = relationship("Game", back_populates="subscriptions")

    def __repr__(self) -> str:
        return (
            f"<Subscription(user_id={self.user_id}, game_id={self.game_id}, "
            f"active={self.is_active}, critical={self.critical_enabled})>"
        )
