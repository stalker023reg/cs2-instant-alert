"""
CS2 Instant Alert — Notification History Model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class NotificationHistory(UUIDMixin, Base):
    """
    Log of every notification sent to every user.

    Tracks delivery status, retry count, latency, and errors
    for monitoring and debugging.
    """

    __tablename__ = "notification_history"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    update_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("updates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Telegram specific message editing fields
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_message_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_edit_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ─── Relationships ───
    user = relationship("User", back_populates="notification_history")
    update = relationship("Update", back_populates="notification_history")

    # ─── Constraints ───
    __table_args__ = (
        # Ensure that for a single user and update, each channel only gets ONE notification
        UniqueConstraint("user_id", "update_id", "channel_type", name="uq_notification_user_update_channel"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationHistory(user_id={self.user_id}, channel={self.channel_type}, "
            f"status={self.status})>"
        )
