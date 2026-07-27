"""
CS2 Instant Alert — Web API Monitor.

Secondary monitoring source using the public Steam Web API.
Used primarily to fetch patch notes and cross-validate updates.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.steam.monitor import SteamMonitor
from app.steam.types import AppUpdateData, SteamSource
from app.utils.retry import async_retry

logger = get_logger("steam")


class WebAPIMonitor(SteamMonitor):
    """
    Monitors Steam updates using the Steam Web API.
    Note: Web API doesn't expose raw build IDs directly, but it
    exposes news feeds (patch notes) which confirm an update's public release.
    """

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=10.0)

    @property
    def source_name(self) -> SteamSource:
        return SteamSource.WEB_API

    @async_retry(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(httpx.RequestError, httpx.TimeoutException),
    )
    async def get_app_data(self, app_id: int) -> AppUpdateData | None:
        """
        Fetch news from Steam Web API.
        We return this data in the raw_payload so the patch notes
        service can extract it later.
        """
        api_key = self.settings.steam_web_api_key.get_secret_value()
        if not api_key:
            await logger.awarning("web_api_key_missing", app_id=app_id)
            return None

        url = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        params = {
            "appid": app_id,
            "count": 3,
            "maxlength": 0,
            "format": "json",
            "key": api_key,
        }

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            await logger.aerror("webapi_fetch_failed", app_id=app_id, error=str(e))
            raise

        # We don't get build_id from this endpoint, but we get timestamp of last news
        news_items = data.get("appnews", {}).get("newsitems", [])

        result = AppUpdateData(
            app_id=app_id,
            source=self.source_name,
            checked_at=datetime.now(UTC),
            raw_payload={"news": news_items},
        )

        return result

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
