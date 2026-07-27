"""
CS2 Instant Alert — User Model.
"""

from __future__ import annotations

from datetime import time

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, String, Time
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UserSettings(BaseModel):
    """Schema for the JSONB settings field."""
    critical_notifications_enabled: bool = Field(default=True)
    retry_interval_seconds: int = Field(default=300) # 5 minutes
    enabled_channels: list[str] = Field(default_factory=lambda: ["telegram"])
    last_status_message_id: int | None = Field(default=None)
    auto_pin_updates: bool = Field(default=False)


class User(UUIDMixin, TimestampMixin, Base):
    """
    Application user.

    Each user is identified by their Telegram ID and can configure
    subscriptions, notification channels, and personal preferences.
    """

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="ru", nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(50), default="Europe/Moscow", nullable=False
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Quiet hours (night mode)
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Flexible settings (JSON)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ─── Relationships ───
    subscriptions = relationship(
        "Subscription", back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )
    notification_channels = relationship(
        "NotificationChannel",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    notification_history = relationship(
        "NotificationHistory", back_populates="user", lazy="noload"
    )
    alert_acknowledgements = relationship(
        "AlertAcknowledgement", back_populates="user", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"
