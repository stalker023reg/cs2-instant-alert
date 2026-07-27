"""
CS2 Instant Alert — Notification Repository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.notification_channel import NotificationChannel
from app.models.notification_history import NotificationHistory
from app.repositories.base import BaseRepository


class NotificationChannelRepository(BaseRepository[NotificationChannel]):
    """Repository for NotificationChannel entity."""

    model = NotificationChannel

    async def get_user_channels(
        self, user_id: uuid.UUID, active_only: bool = True
    ) -> list[NotificationChannel]:
        """Get all notification channels for a user, ordered by priority."""
        stmt = (
            select(NotificationChannel)
            .where(NotificationChannel.user_id == user_id)
            .order_by(NotificationChannel.priority)
        )
        if active_only:
            stmt = stmt.where(NotificationChannel.is_active.is_(True))
        return await self._execute_query(stmt)

    async def get_user_channel_by_type(
        self, user_id: uuid.UUID, channel_type: str
    ) -> NotificationChannel | None:
        """Get a specific channel type for a user."""
        stmt = select(NotificationChannel).where(
            NotificationChannel.user_id == user_id,
            NotificationChannel.channel_type == channel_type,
        )
        return await self._execute_scalar(stmt)


class NotificationHistoryRepository(BaseRepository[NotificationHistory]):
    """Repository for NotificationHistory entity."""

    model = NotificationHistory

    async def get_by_user_and_update(
        self,
        user_id: uuid.UUID,
        update_id: uuid.UUID,
    ) -> list[NotificationHistory]:
        """Get all notification records for a user-update pair."""
        stmt = select(NotificationHistory).where(
            NotificationHistory.user_id == user_id,
            NotificationHistory.update_id == update_id,
        )
        return await self._execute_query(stmt)

    async def get_user_history(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[NotificationHistory]:
        """Get recent notification history for a user."""
        stmt = (
            select(NotificationHistory)
            .where(NotificationHistory.user_id == user_id)
            .order_by(NotificationHistory.sent_at.desc())
            .limit(limit)
        )
        return await self._execute_query(stmt)

    async def get_pending_for_update(
        self, update_id: uuid.UUID
    ) -> list[NotificationHistory]:
        """Get all pending notifications for an update."""
        stmt = select(NotificationHistory).where(
            NotificationHistory.update_id == update_id,
            NotificationHistory.status == "pending",
        )
        return await self._execute_query(stmt)

    async def get_unacknowledged_critical(self) -> list[NotificationHistory]:
        """Get all delivered but unacknowledged notifications (needs join with Subscription in engine)."""
        stmt = select(NotificationHistory).where(
            NotificationHistory.status == "delivered",
            NotificationHistory.acknowledged_at.is_(None)
        )
        return await self._execute_query(stmt)


class NotificationRepository:
    """Facade for dealing with channels and history together."""

    def __init__(self, session):
        self.channel_repo = NotificationChannelRepository(session)
        self.history_repo = NotificationHistoryRepository(session)

    async def get_active_channels_for_user(self, user_id: uuid.UUID) -> list[NotificationChannel]:
        return await self.channel_repo.get_user_channels(user_id, active_only=True)

    async def create_history(self, history: NotificationHistory) -> NotificationHistory:
        return await self.history_repo.create(history)

    async def update_history(self, history: NotificationHistory, **kwargs) -> NotificationHistory:
        return await self.history_repo.update(history, **kwargs)

    async def get_history_by_id(self, history_id: uuid.UUID) -> NotificationHistory | None:
        return await self.history_repo.get_by_id(history_id)
