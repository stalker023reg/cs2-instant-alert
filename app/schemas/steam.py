"""
CS2 Instant Alert — Pydantic Schemas for Steam Data.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SteamAppStateRead(BaseModel):
    """Schema for reading Steam app monitoring state."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    game_id: uuid.UUID
    last_build_id: str | None
    last_change_number: int | None
    last_check_at: datetime | None
    last_update_at: datetime | None
    race_mode_active: bool
    race_mode_until: datetime | None


class SteamCheckResult(BaseModel):
    """Result of a single Steam monitoring check."""

    app_id: int
    build_id: str | None = None
    change_number: int | None = None
    manifests: dict | None = None
    depot_data: dict | None = None
    source: str  # "pics", "webapi", "store", "cdn"
    is_update: bool = False
    checked_at: datetime


class SteamUpdateDetection(BaseModel):
    """Confirmed update detection after cross-validation."""

    app_id: int
    game_id: uuid.UUID
    new_build_id: str
    previous_build_id: str | None
    change_number: int | None
    manifests: dict | None
    depot_changes: dict | None
    size_bytes: int | None
    confirmed_sources: list[str]
    detected_at: datetime
