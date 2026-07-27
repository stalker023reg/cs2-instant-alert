"""
CS2 Instant Alert — Alert Acknowledgement Model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class AlertAcknowledgement(UUIDMixin, Base):
    """
    Record of a user acknowledging a critical alert.

    When a user presses "Получил" (in Telegram, Pushover, or API),
    a record is created here to stop the retry engine.
    """

    __tablename__ = "alert_acknowledgements"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    update_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("updates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ack_source: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Source of acknowledgement: telegram_button, pushover_callback, api, websocket",
    )
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ─── Relationships ───
    user = relationship("User", back_populates="alert_acknowledgements")
    update = relationship("Update", back_populates="alert_acknowledgements")

    def __repr__(self) -> str:
        return (
            f"<AlertAcknowledgement(user_id={self.user_id}, "
            f"update_id={self.update_id}, source={self.ack_source})>"
        )
