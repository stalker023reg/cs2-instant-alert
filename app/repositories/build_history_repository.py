"""
CS2 Instant Alert — Build History Repository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.build_history import BuildHistory
from app.repositories.base import BaseRepository


class BuildHistoryRepository(BaseRepository[BuildHistory]):
    """Repository for BuildHistory entity."""

    model = BuildHistory

    async def get_by_build_id(
        self, game_id: uuid.UUID, build_id: str, branch: str = "public"
    ) -> BuildHistory | None:
        """Find a build history record by game, build ID, and branch."""
        stmt = select(BuildHistory).where(
            BuildHistory.game_id == game_id,
            BuildHistory.build_id == build_id,
            BuildHistory.branch == branch,
        )
        return await self._execute_scalar(stmt)

    async def get_history(
        self,
        game_id: uuid.UUID,
        branch: str = "public",
        *,
        limit: int = 50,
    ) -> list[BuildHistory]:
        """Get build history for a game/branch, newest first."""
        stmt = (
            select(BuildHistory)
            .where(
                BuildHistory.game_id == game_id,
                BuildHistory.branch == branch,
            )
            .order_by(BuildHistory.first_seen_at.desc())
            .limit(limit)
        )
        return await self._execute_query(stmt)

    async def get_latest(
        self, game_id: uuid.UUID, branch: str = "public"
    ) -> BuildHistory | None:
        """Get the latest build for a game/branch."""
        stmt = (
            select(BuildHistory)
            .where(
                BuildHistory.game_id == game_id,
                BuildHistory.branch == branch,
            )
            .order_by(BuildHistory.first_seen_at.desc())
            .limit(1)
        )
        return await self._execute_scalar(stmt)
