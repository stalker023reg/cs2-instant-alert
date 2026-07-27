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
