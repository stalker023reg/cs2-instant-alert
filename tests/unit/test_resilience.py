"""Tests for Steam resilience and Watchdog outage handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import AppSettings
from app.services.watchdog import SilentWatchdogService
from app.steam.client import AsyncSteamClient


@pytest.mark.asyncio
async def test_watchdog_does_not_restart_on_steam_downtime() -> None:
    settings = AppSettings(_env_file=None, steam_anonymous_login=True)
    steam_client = AsyncSteamClient(settings)
    
    health_service = MagicMock()
    # Simulate Steam is down and monitoring is stale, but DB/scheduler/event_bus are healthy
    health_service.check_all = AsyncMock(return_value={
        "database": True,
        "steam_client": False,
        "telegram_bot": True,
        "event_bus": True,
        "scheduler": True,
        "monitoring_fresh": False,
        "overall": False,
    })
    
    admin_notifier = MagicMock()
    admin_notifier.broadcast = AsyncMock()
    
    watchdog = SilentWatchdogService(
        steam_client=steam_client,
        settings=settings,
        health_service=health_service,
        admin_notifier=admin_notifier,
    )
    
    from datetime import UTC, datetime, timedelta
    watchdog._system_downtime_start = datetime.now(UTC) - timedelta(minutes=15)
    
    with patch("os._exit") as mock_exit:
        await watchdog._check_health()
        mock_exit.assert_not_called()


@pytest.mark.asyncio
async def test_watchdog_restarts_on_internal_critical_failure() -> None:
    settings = AppSettings(_env_file=None, steam_anonymous_login=True)
    steam_client = AsyncSteamClient(settings)
    
    health_service = MagicMock()
    # Simulate database is down for > 10 minutes
    health_service.check_all = AsyncMock(return_value={
        "database": False,
        "steam_client": True,
        "telegram_bot": True,
        "event_bus": True,
        "scheduler": True,
        "monitoring_fresh": True,
        "overall": False,
    })
    
    admin_notifier = MagicMock()
    admin_notifier.broadcast = AsyncMock()
    
    watchdog = SilentWatchdogService(
        steam_client=steam_client,
        settings=settings,
        health_service=health_service,
        admin_notifier=admin_notifier,
    )
    
    from datetime import UTC, datetime, timedelta
    watchdog._system_downtime_start = datetime.now(UTC) - timedelta(minutes=11)
    
    with patch("os._exit") as mock_exit:
        await watchdog._check_health()
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_watchdog_triggers_steam_client_restart_on_prolonged_disconnect() -> None:
    settings = AppSettings(_env_file=None, steam_anonymous_login=True)
    steam_client = AsyncSteamClient(settings)
    steam_client.restart = AsyncMock()
    
    health_service = MagicMock()
    health_service.check_all = AsyncMock(return_value={
        "database": True,
        "steam_client": False,
        "telegram_bot": True,
        "event_bus": True,
        "scheduler": True,
        "monitoring_fresh": False,
        "overall": False,
    })
    
    admin_notifier = MagicMock()
    admin_notifier.broadcast = AsyncMock()
    
    watchdog = SilentWatchdogService(
        steam_client=steam_client,
        settings=settings,
        health_service=health_service,
        admin_notifier=admin_notifier,
    )
    
    from datetime import UTC, datetime, timedelta
    now = datetime.now(UTC)
    steam_client.disconnect_time = now - timedelta(minutes=6)
    
    await watchdog._check_health()
    steam_client.restart.assert_awaited_once()
