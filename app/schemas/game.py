"""
CS2 Instant Alert — Pydantic Schemas for Games.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GameBase(BaseModel):
    """Shared game fields."""

    name: str
    steam_app_id: int
    slug: str
    icon_url: str | None = None


class GameCreate(GameBase):
    """Schema for creating a game."""

    monitor_config: dict = {}


class GameRead(GameBase):
    """Schema for reading game data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    monitor_config: dict
    created_at: datetime


class GameBrief(BaseModel):
    """Minimal game info for lists and subscriptions."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    steam_app_id: int
    is_active: bool
