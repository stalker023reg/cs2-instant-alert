"""
CS2 Instant Alert — Pydantic Schemas for Updates.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UpdateRead(BaseModel):
    """Schema for reading update data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    game_id: uuid.UUID
    build_id: str
    previous_build_id: str | None
    size_bytes: int | None
    version: str | None
    patch_notes: str | None
    patch_notes_url: str | None
    patch_notes_fetched: bool
    depot_changes: dict | None
    manifest_changes: dict | None
    detected_at: datetime
    published_at: datetime | None


class UpdateBrief(BaseModel):
    """Brief update info for history lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    build_id: str
    previous_build_id: str | None
    size_bytes: int | None
    patch_notes_fetched: bool
    detected_at: datetime


class BuildHistoryRead(BaseModel):
    """Schema for reading build history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    game_id: uuid.UUID
    build_id: str
    branch: str
    change_number: int | None
    first_seen_at: datetime
    last_seen_at: datetime
