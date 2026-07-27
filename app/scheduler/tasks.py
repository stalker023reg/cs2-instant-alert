"""
CS2 Instant Alert — Monitoring Tasks.

Background tasks for orchestrating Steam monitoring,
detecting updates, and managing race mode.
"""

from __future__ import annotations

import asyncio
import uuid

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.events.bus import EventBus
from app.models.game import Game
from app.repositories.game_repository import GameRepository
from app.repositories.steam_state_repository import SteamStateRepository
from app.services.update_service import UpdateService
from app.steam.multi_source_monitor import MultiSourceMonitor
from app.steam.race_mode import RaceModeController
from app.steam.types import SteamSource

logger = get_logger("system")


class MonitoringOrchestrator:
    """
    Coordinates the background monitoring loops for all active games.
    """

    def __init__(
        self,
        session_factory,
        monitor: MultiSourceMonitor,
        event_bus: EventBus,
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.monitor = monitor
        self.event_bus = event_bus
        self.settings = settings
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._running = False

    async def start(self) -> None:
        """Start monitoring all active games."""
        self._running = True

        async with self.session_factory() as session:
            game_repo = GameRepository(session)
            games = await game_repo.get_active_games()

            for game in games:
                await self.start_monitoring_game(game)

    async def stop(self) -> None:
        """Stop all monitoring tasks."""
        self._running = False
        for task in self._tasks.values():
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            self._tasks.clear()

    async def start_monitoring_game(self, game: Game) -> None:
        """Start the background monitoring loop for a specific game."""
        if game.id in self._tasks and not self._tasks[game.id].done():
            return

        task = asyncio.create_task(
            self._monitoring_loop(game),
            name=f"Monitor_{game.slug}",
        )
        self._tasks[game.id] = task
        await logger.ainfo("monitoring_started", game_id=str(game.id), slug=game.slug)

    async def _monitoring_loop(self, game: Game) -> None:
        """The continuous polling loop for a game."""
        while self._running:
            interval = self.settings.steam_check_interval_seconds
            try:
                # 1. Open short-lived session for this check
                async with self.session_factory() as session:
                    state_repo = SteamStateRepository(session)
                    app_state = await state_repo.get_or_create(game.id)

                    # Initialize controllers
                    race_controller = RaceModeController(state_repo, self.settings)
                    # Check if we should deactivate race mode
                    app_state = await race_controller.check_and_deactivate(app_state)

                    # Determine interval
                    interval = race_controller.get_current_interval(app_state, game.monitor_config)

                # 2. Fetch data (outside of DB transaction)
                # Primary source is PICS. We can fetch others if race mode is active to get patch notes.
                sources = [SteamSource.PICS]
                if app_state.race_mode_active:
                    sources.append(SteamSource.WEB_API)

                results = await self.monitor.check_app(game.steam_app_id, sources=sources)

                # 3. Process data
                if SteamSource.PICS in results:
                    async with self.session_factory() as session:
                        state_repo = SteamStateRepository(session)
                        app_state = await state_repo.get_by_game_id(game.id)
                        if app_state is None:
                            app_state = await state_repo.get_or_create(game.id)

                        update_service = UpdateService(session, self.event_bus)
                        race_controller = RaceModeController(state_repo, self.settings)

                        is_new = await update_service.process_steam_data(
                            game.id,
                            app_state,
                            results[SteamSource.PICS]
                        )

                        if is_new:
                            await race_controller.activate_race_mode(app_state)

                        await session.commit()
                else:
                    await logger.awarning(
                        "monitoring_check_failed",
                        game_id=str(game.id),
                        source=SteamSource.PICS,
                    )

                # Wait for next interval
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                await logger.ainfo("monitoring_stopped", game_id=str(game.id))
                raise
            except Exception as e:
                # Keep the same task alive. The previous implementation attempted
                # to spawn a replacement while the current task was still present
                # in _tasks, so a single exception stopped monitoring permanently.
                await logger.aerror(
                    "monitoring_iteration_failed",
                    game_id=str(game.id),
                    error=str(e),
                    exc_info=True,
                )
                if self._running:
                    await asyncio.sleep(min(60, max(5, interval)))
