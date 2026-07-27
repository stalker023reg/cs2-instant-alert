"""
CS2 Instant Alert — Notification Channel Model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class NotificationChannel(UUIDMixin, TimestampMixin, Base):
    """
    User-configured notification channel.

    Each user can have multiple channels of different types.
    Channel-specific credentials are stored encrypted in the `config` JSON field.
    """

    __tablename__ = "notification_channels"
    __table_args__ = (
        UniqueConstraint("user_id", "channel_type", name="uq_notification_channel_user_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    # Encrypted JSON: API keys, webhook URLs, user keys, etc.
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Delivery order: lower = higher priority",
    )

    # ─── Relationships ───
    user = relationship("User", back_populates="notification_channels")

    def __repr__(self) -> str:
        return (
            f"<NotificationChannel(user_id={self.user_id}, "
            f"type={self.channel_type}, active={self.is_active})>"
        )
