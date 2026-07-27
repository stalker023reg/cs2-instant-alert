"""
CS2 Instant Alert — Pydantic Schemas for Users.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    """Shared user fields."""

    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language: str = "ru"
    timezone: str = "Europe/Moscow"


class UserCreate(UserBase):
    """Schema for creating a user."""

    telegram_id: int


class UserUpdate(BaseModel):
    """Schema for updating user settings."""

    language: str | None = None
    timezone: str | None = None
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    settings: dict | None = None


class UserRead(UserBase):
    """Schema for reading user data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    telegram_id: int
    is_admin: bool
    is_active: bool
    quiet_hours_enabled: bool
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    settings: dict
    created_at: datetime
    updated_at: datetime


class UserBrief(BaseModel):
    """Minimal user info for lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    telegram_id: int
    username: str | None
    is_active: bool
