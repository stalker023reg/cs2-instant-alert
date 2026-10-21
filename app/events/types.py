"""
CS2 Instant Alert — Event Types.

Pydantic models representing events that flow through the Event Bus.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.steam.types import AppUpdateData


class UpdateDetectedEvent(BaseModel):
    """
    Fired when a new game update is confirmed.
    """
    update_id: uuid.UUID
    game_id: uuid.UUID
    build_id: str
    previous_build_id: str | None
    is_critical: bool
    detected_at: datetime

    # Raw payload for extracting patch notes if available
    raw_data: AppUpdateData
    depot_changes: dict | None = None


class PatchNotesFoundEvent(BaseModel):
    """
    Fired when patch notes are successfully retrieved for an update.
    """
    update_id: uuid.UUID
    game_id: uuid.UUID
    build_id: str
    patch_notes_url: str | None
    patch_notes_text: str | None


class NotificationAcknowledgedEvent(BaseModel):
    """
    Fired when a user acknowledges a critical notification.
    """
    notification_id: uuid.UUID
    user_id: uuid.UUID
    update_id: uuid.UUID
    acknowledged_at: datetime
