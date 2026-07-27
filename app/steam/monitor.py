"""
CS2 Instant Alert — Abstract Steam Monitor.

Defines the base interface for all Steam monitoring sources
(PICS, WebAPI, Store API).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.steam.types import AppUpdateData, SteamSource


class SteamMonitor(ABC):
    """
    Abstract base class for Steam data sources.
    """

    @property
    @abstractmethod
    def source_name(self) -> SteamSource:
        """The identifier of this monitoring source."""
        pass

    @abstractmethod
    async def get_app_data(self, app_id: int) -> AppUpdateData | None:
        """
        Fetch the current state of the app from this source.
        
        Args:
            app_id: The Steam App ID to check.
            
        Returns:
            AppUpdateData if successful, None if the source failed
            or the app doesn't exist on this source.
        """
        pass
