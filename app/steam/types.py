"""
CS2 Instant Alert — Steam Types.

Defines Pydantic models and Enums for Steam API interactions,
ensuring type safety across all monitor sources.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from typing import Any

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

    def get_manifest_dict(self) -> dict[str, str]:
        """Return dict of depot_id (str) -> manifest_id for all depots with manifests."""
        return {
            str(depot_id): depot.manifest_id
            for depot_id, depot in self.depots.items()
            if depot.manifest_id
        }

    def compute_depot_diff(
        self, previous_manifests: dict[str, str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """
        Compare current depots against previous manifests to find what changed.

        Returns:
            Dict of depot_id (str) -> {name, old_manifest, new_manifest, size_bytes}
        """
        if not previous_manifests:
            return {
                str(depot_id): {
                    "name": depot.name,
                    "old_manifest": None,
                    "new_manifest": depot.manifest_id,
                    "size_bytes": depot.size_bytes,
                }
                for depot_id, depot in self.depots.items()
                if depot.manifest_id
            }

        diff: dict[str, dict[str, Any]] = {}
        for depot_id, depot in self.depots.items():
            if not depot.manifest_id:
                continue
            depot_str = str(depot_id)
            old_manifest = previous_manifests.get(depot_str)
            if old_manifest != depot.manifest_id:
                diff[depot_str] = {
                    "name": depot.name,
                    "old_manifest": old_manifest,
                    "new_manifest": depot.manifest_id,
                    "size_bytes": depot.size_bytes,
                }
        return diff
