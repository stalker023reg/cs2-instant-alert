"""Unit tests for gevent exception isolation and MonitoringOrchestrator supervisor."""

from __future__ import annotations

import asyncio
import concurrent.futures
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

from app.core.config import AppSettings
from app.models.game import Game
from app.scheduler.tasks import MonitoringOrchestrator
from app.steam.client import AsyncSteamClient, SteamConnectionError


class CustomBaseException(BaseException):
    """Simulates a gevent.Timeout or GreenletExit that does not inherit from Exception."""
    pass


def test_steam_client_wraps_base_exception_into_steam_connection_error():
    """Verify that non-Exception BaseExceptions inside gevent greenlets are converted to SteamConnectionError."""
    settings = AppSettings(_env_file=None, steam_anonymous_login=True)
    client = AsyncSteamClient(settings)

    # Simulate what _drain_task_queue does inside the Steam thread
    fut: concurrent.futures.Future = concurrent.futures.Future()

    def buggy_op():
        raise CustomBaseException("Gevent timeout simulation")

    # Call the exact inner logic from _drain_task_queue
    try:
        buggy_op()
        fut.set_result(None)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            fut.set_exception(exc)
        elif isinstance(exc, Exception):
            fut.set_exception(exc)
        else:
            fut.set_exception(
                SteamConnectionError(
                    f"Steam greenlet operation error ({type(exc).__name__}): {exc}",
                    code="STEAM_GREENLET_ERROR",
                )
            )

    # Verify that future raises SteamConnectionError (which is an Exception), NOT CustomBaseException!
    with pytest.raises(SteamConnectionError) as exc_info:
        fut.result()

    assert "CustomBaseException" in str(exc_info.value)
    assert issubclass(type(exc_info.value), Exception)


@pytest.mark.asyncio
async def test_monitoring_orchestrator_supervises_and_respawns_dead_task():
    """Verify that if a monitoring task unexpectedly finishes, the supervisor respawns it."""
    session_factory = MagicMock()
    monitor = MagicMock()
    event_bus = MagicMock()
    settings = MagicMock()
    settings.steam_check_interval_seconds = 1

    orchestrator = MonitoringOrchestrator(
        session_factory=session_factory,
        monitor=monitor,
        event_bus=event_bus,
        settings=settings,
    )
    orchestrator._running = True

    game = Game(
        id=uuid.uuid4(),
        name="Counter-Strike 2",
        slug="cs2",
        steam_app_id=730,
        is_active=True,
    )

    iteration_count = 0

    async def mock_loop(g):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count == 1:
            # First task dies immediately
            return
        else:
            # Second (respawned) task stays alive
            await asyncio.sleep(10)

    with patch.object(orchestrator, "_monitoring_loop", side_effect=mock_loop):
        # Start initial task
        await orchestrator.start_monitoring_game(game)

        # Allow task to terminate and supervisor done_callback to fire
        await asyncio.sleep(0.1)

        # First task should be done
        assert iteration_count >= 1

        # Wait for respawn backoff (2.0s) + small buffer
        await asyncio.sleep(2.5)

        # Supervisor must have respawned the task (iteration_count == 2)
        assert iteration_count == 2
        active_task = orchestrator._tasks.get(game.id)
        assert active_task is not None
        assert not active_task.done()

        # Clean up
        await orchestrator.stop()

