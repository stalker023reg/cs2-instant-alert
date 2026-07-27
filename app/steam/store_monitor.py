"""
CS2 Instant Alert — Store API Monitor.

Tertiary monitoring source using the Steam Store API.
Used for fetching game metadata (icon, name) and verifying app existence.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.logging import get_logger
from app.steam.monitor import SteamMonitor
from app.steam.types import AppUpdateData, SteamSource
from app.utils.retry import async_retry

logger = get_logger("steam")


class StoreMonitor(SteamMonitor):
    """
    Monitors Steam updates using the Store API.
    Used mainly for metadata and cross-validation of app state.
    """

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=10.0)

    @property
    def source_name(self) -> SteamSource:
        return SteamSource.STORE

    @async_retry(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(httpx.RequestError, httpx.TimeoutException),
    )
    async def get_app_data(self, app_id: int) -> AppUpdateData | None:
        """
        Fetch app details from Steam Store API.
        """
        url = "https://store.steampowered.com/api/appdetails"
        params = {"appids": app_id}

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            await logger.aerror("store_fetch_failed", app_id=app_id, error=str(e))
            raise

        app_id_str = str(app_id)
        if app_id_str not in data or not data[app_id_str].get("success"):
            return None

        store_data = data[app_id_str]["data"]

        result = AppUpdateData(
            app_id=app_id,
            source=self.source_name,
            checked_at=datetime.now(UTC),
            raw_payload={"store": store_data},
        )

        return result

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
