"""
CS2 Instant Alert — Steam Monitor Tests.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.config import AppSettings
from app.steam.monitor import SteamMonitor
from app.steam.multi_source_monitor import MultiSourceMonitor
from app.steam.pics_monitor import PICSMonitor
from app.steam.race_mode import RaceModeController
from app.steam.store_monitor import StoreMonitor
from app.steam.types import AppUpdateData, SteamSource
from app.steam.webapi_monitor import WebAPIMonitor


@pytest.fixture
def mock_settings() -> AppSettings:
    settings = AppSettings(
        steam_web_api_key="test-key",
        steam_anonymous_login=True,
    )
    return settings


class TestSteamTypes:
    def test_app_update_data_helper(self) -> None:
        from app.steam.types import BranchInfo

        data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(timezone.utc),
            branches={
                "public": BranchInfo(name="public", build_id="1234"),
                "beta": BranchInfo(name="beta", build_id="5678"),
            },
        )

        assert data.get_public_build_id() == "1234"

    def test_app_update_data_missing_public(self) -> None:
        data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=datetime.now(timezone.utc),
            branches={},
        )
        assert data.get_public_build_id() is None


@pytest.mark.asyncio
class TestWebAPIMonitor:
    async def test_successful_fetch(self, mock_settings: AppSettings, mocker: MagicMock) -> None:
        monitor = WebAPIMonitor(settings=mock_settings)

        # Mock httpx response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "appnews": {
                "newsitems": [{"gid": "123", "title": "Update"}]
            }
        }
        
        mocker.patch.object(monitor.client, "get", return_value=mock_response)

        data = await monitor.get_app_data(730)
        assert data is not None
        assert data.source == SteamSource.WEB_API
        assert data.raw_payload is not None
        assert "news" in data.raw_payload
        assert len(data.raw_payload["news"]) == 1

        await monitor.close()


@pytest.mark.asyncio
class TestMultiSourceMonitor:
    async def test_concurrent_checks(self, mock_settings: AppSettings, mocker: MagicMock) -> None:
        # Mock monitors
        pics = AsyncMock(spec=PICSMonitor)
        pics.source_name = SteamSource.PICS
        pics.get_app_data.return_value = AppUpdateData(
            app_id=730, source=SteamSource.PICS, checked_at=datetime.now(timezone.utc)
        )

        webapi = AsyncMock(spec=WebAPIMonitor)
        webapi.source_name = SteamSource.WEB_API
        webapi.get_app_data.return_value = AppUpdateData(
            app_id=730, source=SteamSource.WEB_API, checked_at=datetime.now(timezone.utc)
        )

        store = AsyncMock(spec=StoreMonitor)
        store.source_name = SteamSource.STORE
        store.get_app_data.return_value = None  # Simulate failure or no data

        orchestrator = MultiSourceMonitor(pics, webapi, store, mock_settings)

        results = await orchestrator.check_app(730)
        
        assert len(results) == 2
        assert SteamSource.PICS in results
        assert SteamSource.WEB_API in results
        assert SteamSource.STORE not in results

        pics.get_app_data.assert_awaited_once_with(730)
        webapi.get_app_data.assert_awaited_once_with(730)
        store.get_app_data.assert_awaited_once_with(730)


@pytest.mark.asyncio
class TestSteamNewsFetcher:
    async def test_webapi_with_cache_busting_success(self, mocker: MagicMock) -> None:
        from app.services.steam_news_fetcher import SteamNewsFetcher

        fetcher = SteamNewsFetcher()
        detected_at = datetime(2026, 11, 23, 23, 0, 0, tzinfo=timezone.utc)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "appnews": {
                "newsitems": [
                    {
                        "gid": "1849827110444052",
                        "title": "Counter-Strike 2 Update",
                        "feedname": "steam_community_announcements",
                        "tags": ["patchnotes"],
                        "date": int(detected_at.timestamp()) + 120,
                        "contents": "[p]Cobblestone updates[/p]",
                    }
                ]
            }
        }

        mock_get = AsyncMock(return_value=mock_resp)
        mocker.patch("httpx.AsyncClient.get", mock_get)

        item = await fetcher.fetch_latest_patchnotes(detected_at)
        assert item is not None
        assert item.gid == "1849827110444052"
        assert item.title == "Counter-Strike 2 Update"
        assert "[p]Cobblestone updates[/p]" in item.contents

        # Verify cache busting query parameter and no-cache headers were sent
        called_url, called_kwargs = mock_get.call_args[0][0], mock_get.call_args[1]
        assert "_cb=" in called_url
        headers = called_kwargs.get("headers", {})
        assert headers.get("Cache-Control") == "no-cache, no-store, must-revalidate"
        assert headers.get("Pragma") == "no-cache"

    async def test_rss_fallback_when_webapi_is_stale(self, mocker: MagicMock) -> None:
        from app.services.steam_news_fetcher import SteamNewsFetcher

        fetcher = SteamNewsFetcher()
        detected_at = datetime(2026, 11, 23, 23, 0, 0, tzinfo=timezone.utc)

        # 1st call (WebAPI): Stale response with old announcement from 10 hours ago
        mock_webapi_resp = MagicMock()
        mock_webapi_resp.status_code = 200
        mock_webapi_resp.json.return_value = {
            "appnews": {
                "newsitems": [
                    {
                        "gid": "old_post",
                        "title": "Old Post",
                        "feedname": "steam_community_announcements",
                        "date": int(detected_at.timestamp()) - 36000,
                        "contents": "old",
                    }
                ]
            }
        }

        # 2nd call (RSS): Fresh announcement from 2 minutes after detection
        mock_rss_resp = MagicMock()
        mock_rss_resp.status_code = 200
        mock_rss_resp.text = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Counter-Strike 2 News</title>
    <item>
      <title>Counter-Strike 2 Update</title>
      <description>&lt;p&gt;Cobblestone fixes&lt;/p&gt;</description>
      <link>https://store.steampowered.com/news/app/730/view/694278269818635488</link>
      <pubDate>Mon, 23 Nov 2026 23:02:07 +0000</pubDate>
      <guid isPermaLink="true">https://store.steampowered.com/news/app/730/view/694278269818635488</guid>
    </item>
  </channel>
</rss>"""

        async def fake_get(url: str, **kwargs):
            if "ISteamNews" in url:
                return mock_webapi_resp
            return mock_rss_resp

        mocker.patch("httpx.AsyncClient.get", side_effect=fake_get)

        item = await fetcher.fetch_latest_patchnotes(detected_at)
        assert item is not None
        assert item.gid == "694278269818635488"
        assert item.title == "Counter-Strike 2 Update"
        assert "<p>Cobblestone fixes</p>" in item.contents
        assert item.url == "https://store.steampowered.com/news/app/730/view/694278269818635488"

