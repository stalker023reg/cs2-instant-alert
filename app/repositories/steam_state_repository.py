"""
CS2 Instant Alert — Steam State Repository.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.steam_app_state import SteamAppState
from app.repositories.base import BaseRepository


class SteamStateRepository(BaseRepository[SteamAppState]):
    """Repository for SteamAppState entity."""

    model = SteamAppState

    async def get_by_game_id(self, game_id: uuid.UUID) -> SteamAppState | None:
        """Get monitoring state for a game."""
        stmt = select(SteamAppState).where(SteamAppState.game_id == game_id)
        return await self._execute_scalar(stmt)

    async def get_or_create(self, game_id: uuid.UUID) -> SteamAppState:
        """Get existing state or create a new blank one."""
        state = await self.get_by_game_id(game_id)
        if state:
            return state

        new_state = SteamAppState(game_id=game_id)
        return await self.create(new_state)

    async def update_state(
        self,
        game_id: uuid.UUID,
        *,
        build_id: str | None = None,
        change_number: int | None = None,
        manifests: dict | None = None,
        depot_data: dict | None = None,
        check_time: datetime | None = None,
        update_time: datetime | None = None,
    ) -> SteamAppState | None:
        """Update monitoring state fields."""
        state = await self.get_by_game_id(game_id)
        if not state:
            return None

        values: dict = {}
        if build_id is not None:
            values["last_build_id"] = build_id
        if change_number is not None:
            values["last_change_number"] = change_number
        if manifests is not None:
            values["last_manifests"] = manifests
        if depot_data is not None:
            values["last_depot_data"] = depot_data
        if check_time is not None:
            values["last_check_at"] = check_time
        if update_time is not None:
            values["last_update_at"] = update_time

        if values:
            return await self.update_by_id(state.id, **values)
        return state

    async def activate_race_mode(
        self, game_id: uuid.UUID, until: datetime
    ) -> SteamAppState | None:
        """Enable Race Mode for a game until the given time."""
        state = await self.get_by_game_id(game_id)
        if not state:
            return None
        return await self.update_by_id(
            state.id, race_mode_active=True, race_mode_until=until
        )

    async def deactivate_race_mode(self, game_id: uuid.UUID) -> SteamAppState | None:
        """Disable Race Mode for a game."""
        state = await self.get_by_game_id(game_id)
        if not state:
            return None
        return await self.update_by_id(
            state.id, race_mode_active=False, race_mode_until=None
        )
