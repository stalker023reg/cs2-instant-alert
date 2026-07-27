"""
CS2 Instant Alert — Multi-Source Monitor.

Orchestrates Steam checking across multiple sources to provide
cross-validation and fallback mechanisms.
"""

from __future__ import annotations

import asyncio

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.steam.monitor import SteamMonitor
from app.steam.pics_monitor import PICSMonitor
from app.steam.store_monitor import StoreMonitor
from app.steam.types import AppUpdateData, SteamSource
from app.steam.webapi_monitor import WebAPIMonitor

logger = get_logger("steam")


class MultiSourceMonitor:
    """
    Coordinates data fetching across PICS, WebAPI, and Store API.
    Provides a consolidated view of app updates.
    """

    def __init__(
        self,
        pics_monitor: PICSMonitor,
        webapi_monitor: WebAPIMonitor,
        store_monitor: StoreMonitor,
        settings: AppSettings,
    ) -> None:
        self.pics = pics_monitor
        self.webapi = webapi_monitor
        self.store = store_monitor
        self.settings = settings

        self._sources = {
            SteamSource.PICS: self.pics,
            SteamSource.WEB_API: self.webapi,
            SteamSource.STORE: self.store,
        }

    async def check_app(
        self,
        app_id: int,
        sources: list[SteamSource] | None = None
    ) -> dict[SteamSource, AppUpdateData]:
        """
        Check an app across multiple sources concurrently.
        
        Args:
            app_id: Steam Application ID.
            sources: List of sources to check. If None, checks all.
            
        Returns:
            A dictionary mapping source names to the fetched AppUpdateData.
            If a source fails or returns None, it is omitted from the result.
        """
        targets = sources or list(self._sources.keys())

        # Build tasks for concurrent execution
        tasks = []
        for source in targets:
            monitor = self._sources[source]
            tasks.append(self._safe_fetch(monitor, app_id))

        results = await asyncio.gather(*tasks)

        # Filter out Nones and map by source
        valid_results = {}
        for res in results:
            if res is not None:
                valid_results[res.source] = res

        return valid_results

    async def _safe_fetch(self, monitor: SteamMonitor, app_id: int) -> AppUpdateData | None:
        """Safely execute a single monitor fetch without crashing gather."""
        try:
            return await monitor.get_app_data(app_id)
        except Exception as e:
            await logger.aerror(
                "monitor_fetch_error",
                source=monitor.source_name,
                app_id=app_id,
                error=str(e)
            )
            return None

    async def close(self) -> None:
        """Close all underlying clients."""
        await self.webapi.close()
        await self.store.close()
        # Note: pics (SteamClient) is managed by the DI container lifecycle separately
