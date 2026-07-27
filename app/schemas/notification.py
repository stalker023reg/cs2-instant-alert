"""
CS2 Instant Alert — Pydantic Schemas for Notifications.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationChannelCreate(BaseModel):
    """Schema for creating a notification channel."""

    channel_type: str
    config: dict = {}
    priority: int = 0


class NotificationChannelUpdate(BaseModel):
    """Schema for updating a notification channel."""

    config: dict | None = None
    is_active: bool | None = None
    priority: int | None = None


class NotificationChannelRead(BaseModel):
    """Schema for reading a notification channel (config is masked)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    channel_type: str
    is_active: bool
    priority: int
    created_at: datetime


class NotificationHistoryRead(BaseModel):
    """Schema for reading notification delivery history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    update_id: uuid.UUID
    channel_type: str
    status: str
    error_message: str | None
    retry_count: int
    sent_at: datetime | None
    acknowledged_at: datetime | None
    latency_ms: float | None
