"""
CS2 Instant Alert — Race Mode Controller.

Manages 'Race Mode' state for applications. Race mode temporarily
increases polling frequency immediately after an update is detected
to rapidly capture subsequent CDN metadata and patch notes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.models.steam_app_state import SteamAppState
from app.repositories.steam_state_repository import SteamStateRepository

logger = get_logger("steam")


class RaceModeController:
    """Controls the activation and lifecycle of Race Mode."""

    def __init__(
        self,
        state_repo: SteamStateRepository,
        settings: AppSettings,
    ) -> None:
        self.state_repo = state_repo
        self.settings = settings

    async def activate_race_mode(self, app_state: SteamAppState) -> SteamAppState:
        """
        Activate race mode for an app.
        
        Sets race_mode_active to True and extends race_mode_until by
        30 minutes maximum runtime.
        """
        duration = timedelta(minutes=30)
        until = datetime.now(UTC) + duration

        updated_state = await self.state_repo.update(
            app_state,
            race_mode_active=True,
            race_mode_until=until,
        )

        await logger.ainfo(
            "race_mode_activated",
            game_id=str(updated_state.game_id),
            until=until.isoformat(),
        )
        return updated_state

    async def check_and_deactivate(self, app_state: SteamAppState) -> SteamAppState:
        """
        Check if race mode has expired, and deactivate it if so.
        Conditions for deactivation:
        1. 30 minutes absolute maximum reached (race_mode_until)
        2. 10 minutes elapsed since the last update (idle timeout)
        Returns the (potentially updated) app state.
        """
        if not app_state.race_mode_active:
            return app_state

        if not app_state.race_mode_until:
            # Corrupted state, deactivate
            return await self._deactivate(app_state)

        now = datetime.now(UTC)

        # 1. Absolute Maximum (30m)
        if now >= app_state.race_mode_until:
            await logger.ainfo("race_mode_max_runtime_reached")
            return await self._deactivate(app_state)

        # 2. Idle Timeout (10m without new updates)
        if app_state.last_update_at:
            idle_duration = now - app_state.last_update_at
            if idle_duration > timedelta(minutes=10):
                await logger.ainfo("race_mode_idle_timeout_reached")
                return await self._deactivate(app_state)

        return app_state

    async def _deactivate(self, app_state: SteamAppState) -> SteamAppState:
        updated_state = await self.state_repo.update(
            app_state,
            race_mode_active=False,
            race_mode_until=None,
        )
        await logger.ainfo(
            "race_mode_deactivated",
            game_id=str(updated_state.game_id),
        )
        return updated_state

    def get_current_interval(self, app_state: SteamAppState, game_config: dict) -> int:
        """
        Determine the appropriate polling interval in seconds.
        Prioritizes game-specific config, then global defaults.
        """
        if app_state.race_mode_active:
            return game_config.get(
                "race_mode_interval_seconds",
                self.settings.steam_race_mode_interval_seconds
            )
        else:
            return game_config.get(
                "check_interval_seconds",
                self.settings.steam_check_interval_seconds
            )
