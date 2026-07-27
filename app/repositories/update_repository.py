"""
CS2 Instant Alert — Update Repository.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.update import Update
from app.repositories.base import BaseRepository


class UpdateRepository(BaseRepository[Update]):
    """Repository for Update entity with history queries."""

    model = Update

    async def get_latest_for_game(self, game_id: uuid.UUID) -> Update | None:
        """Get the most recent update for a game."""
        stmt = (
            select(Update)
            .where(Update.game_id == game_id)
            .order_by(Update.detected_at.desc())
            .limit(1)
        )
        return await self._execute_scalar(stmt)

    async def append_timeline_event(self, update_id: uuid.UUID, event_type: str, source: str, metadata: dict | None = None) -> None:
        """Appends an event to the update's timeline."""

        update_obj = await self.get_by_id(update_id)
        if update_obj:
            timeline = dict(update_obj.timeline) if update_obj.timeline else {"events": []}
            if "events" not in timeline:
                timeline["events"] = []

            timeline["events"].append({
                "type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": source,
                "metadata": metadata or {}
            })

            await self.update(update_obj, timeline=timeline)

    async def get_by_build_id(
        self, game_id: uuid.UUID, build_id: str
    ) -> Update | None:
        """Find an update by game and build ID."""
        stmt = select(Update).where(
            Update.game_id == game_id,
            Update.build_id == build_id,
        )
        return await self._execute_scalar(stmt)

    async def get_history(
        self,
        game_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Update]:
        """Get update history for a game, newest first."""
        stmt = (
            select(Update)
            .where(Update.game_id == game_id)
            .order_by(Update.detected_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return await self._execute_query(stmt)

    async def get_updates_without_patch_notes(
        self, game_id: uuid.UUID
    ) -> list[Update]:
        """Get updates that are still waiting for patch notes."""
        stmt = select(Update).where(
            Update.game_id == game_id,
            Update.patch_notes_fetched.is_(False),
        )
        return await self._execute_query(stmt)

    async def update_patch_notes(
        self,
        update_id: uuid.UUID,
        patch_notes: str,
        patch_notes_url: str | None = None,
    ) -> Update | None:
        """Set patch notes for an update."""
        return await self.update_by_id(
            update_id,
            patch_notes=patch_notes,
            patch_notes_url=patch_notes_url,
            patch_notes_fetched=True,
        )
