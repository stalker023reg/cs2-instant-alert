"""
CS2 Instant Alert — Game Repository.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.game import Game
from app.repositories.base import BaseRepository


class GameRepository(BaseRepository[Game]):
    """Repository for Game entity with domain-specific queries."""

    model = Game

    async def get_by_steam_app_id(self, steam_app_id: int) -> Game | None:
        """Find a game by its Steam App ID."""
        stmt = select(Game).where(Game.steam_app_id == steam_app_id)
        return await self._execute_scalar(stmt)

    async def get_by_slug(self, slug: str) -> Game | None:
        """Find a game by its URL slug."""
        stmt = select(Game).where(Game.slug == slug)
        return await self._execute_scalar(stmt)

    async def get_active_games(self) -> list[Game]:
        """Get all active (monitored) games."""
        stmt = select(Game).where(Game.is_active.is_(True))
        return await self._execute_query(stmt)

    async def get_active_app_ids(self) -> list[int]:
        """Get Steam App IDs of all active games."""
        stmt = select(Game.steam_app_id).where(Game.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
