"""
CS2 Instant Alert — Pydantic Schemas for Subscriptions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SubscriptionCreate(BaseModel):
    """Schema for subscribing to a game."""

    game_id: uuid.UUID
    critical_enabled: bool = False
    repeat_enabled: bool = False
    repeat_interval_seconds: int = 120


class SubscriptionUpdate(BaseModel):
    """Schema for updating subscription settings."""

    is_active: bool | None = None
    critical_enabled: bool | None = None
    repeat_enabled: bool | None = None
    repeat_interval_seconds: int | None = None


class SubscriptionRead(BaseModel):
    """Schema for reading subscription data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    game_id: uuid.UUID
    is_active: bool
    critical_enabled: bool
    repeat_enabled: bool
    repeat_interval_seconds: int
    created_at: datetime
