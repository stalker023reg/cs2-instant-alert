"""
CS2 Instant Alert — Steam Types.

Defines Pydantic models and Enums for Steam API interactions,
ensuring type safety across all monitor sources.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class SteamSource(str, Enum):
    """Sources from which Steam update data can be retrieved."""

    PICS = "pics"
    WEB_API = "webapi"
    STORE = "store"


class DepotInfo(BaseModel):
    """Information about a specific Steam depot."""

    model_config = ConfigDict(extra="ignore")

    depot_id: int
    name: str | None = None
    manifest_id: str | None = None
    size_bytes: int | None = None
    updated_at: datetime | None = None


class BranchInfo(BaseModel):
    """Information about a specific Steam branch (e.g., 'public')."""

    model_config = ConfigDict(extra="ignore")

    name: str
    build_id: str
    time_updated: datetime | None = None
    pwd_required: bool = False
    description: str | None = None


class AppUpdateData(BaseModel):
    """
    Standardized payload of an app update, retrieved from any source.
    """

    app_id: int
    source: SteamSource
    checked_at: datetime

    change_number: int | None = None
    branches: dict[str, BranchInfo] = {}
    depots: dict[int, DepotInfo] = {}

    # Raw payload from the source for debugging or fallback processing
    raw_payload: dict | None = None

    def get_public_build_id(self) -> str | None:
        """Helper to safely get the 'public' branch build ID."""
        if "public" in self.branches:
            return self.branches["public"].build_id
        return None
