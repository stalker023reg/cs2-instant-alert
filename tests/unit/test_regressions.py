"""Regression tests for failures observed in the deployed service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import AppSettings
from app.core.logging import SensitiveDataFilter
from app.models.steam_app_state import SteamAppState
from app.services.update_service import UpdateService
from app.steam.client import AsyncSteamClient
from app.steam.types import AppUpdateData, BranchInfo, SteamSource


@pytest.mark.asyncio
async def test_steam_operation_runs_through_own_gevent_hub(monkeypatch) -> None:
    settings = AppSettings(_env_file=None, steam_anonymous_login=True)
    wrapper = AsyncSteamClient(settings)
    wrapper._thread = MagicMock()
    wrapper._thread.is_alive.return_value = True

    class ImmediateLoop:
        def run_callback_threadsafe(self, callback, *args):
            callback(*args)

    wrapper._gevent_hub = SimpleNamespace(loop=ImmediateLoop())
    wrapper.client = MagicMock()
    wrapper.client.get_product_info.return_value = {"apps": {730: {}}}
    wrapper._connected.set()

    # Make gevent.spawn execute synchronously with arguments
    monkeypatch.setattr("app.steam.client.gevent.spawn", lambda fn, *args: fn(*args))

    # Automatically drain task queue when task is put
    orig_put = wrapper._task_queue.put
    def auto_drain(item):
        orig_put(item)
        wrapper._drain_task_queue()
    monkeypatch.setattr(wrapper._task_queue, "put", auto_drain)

    result = await wrapper.get_product_info([730])

    assert result == {"apps": {730: {}}}
    wrapper.client.get_product_info.assert_called_once_with(apps=[730], packages=[])


@pytest.mark.asyncio
async def test_update_service_preserves_previous_build_id() -> None:
    service = UpdateService(AsyncMock(), AsyncMock())
    service._record_build_history = AsyncMock()
    service._handle_new_update = AsyncMock()

    app_state = SteamAppState(game_id=MagicMock(), last_build_id="100")

    async def update_state(state, **values):
        for key, value in values.items():
            setattr(state, key, value)
        return state

    service.state_repo = MagicMock()
    service.state_repo.update_state = AsyncMock(side_effect=update_state)

    data = AppUpdateData(
        app_id=730,
        source=SteamSource.PICS,
        checked_at=datetime.now(UTC),
        branches={"public": BranchInfo(name="public", build_id="200")},
    )

    detected = await service.process_steam_data(MagicMock(), app_state, data)

    assert detected is True
    assert service._handle_new_update.await_args.args[1:3] == ("100", "200")


def test_sensitive_data_filter_redacts_telegram_token() -> None:
    record = logging.LogRecord(
        name="telegram.ext.ExtBot",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="POST https://api.telegram.org/bot123456:ABC_def-ghi/getMe",
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert "123456:ABC_def-ghi" not in record.msg
    assert "<redacted>" in record.msg
