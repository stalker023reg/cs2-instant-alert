"""
CS2 Instant Alert — Acknowledgement Service.

Standalone service to process user acknowledgements for critical
notifications. Completely decoupled from specific delivery channels.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.events.bus import EventBus
from app.events.types import NotificationAcknowledgedEvent
from app.repositories.notification_repository import NotificationRepository

logger = get_logger("system")


class AcknowledgementService:
    """Processes user acknowledgements for notifications."""

    def __init__(self, session_factory, event_bus: EventBus) -> None:
        self.session_factory = session_factory
        self.event_bus = event_bus

    async def acknowledge(
        self,
        notification_id: uuid.UUID,
        *,
        telegram_id: int | None = None,
    ) -> bool:
        """
        Mark a notification as acknowledged by the user.
        
        Args:
            notification_id: The ID of the notification history record.
            
        Returns:
            True if successfully acknowledged, False if already acknowledged.
            
        Raises:
            EntityNotFoundError: If notification ID is not found.
        """
        async with self.session_factory() as session:
            repo = NotificationRepository(session)
            history = await repo.get_history_by_id(notification_id)
            if not history:
                raise EntityNotFoundError("Notification", str(notification_id))

            if telegram_id is not None:
                from app.repositories.user_repository import UserRepository

                owner = await UserRepository(session).get_by_id(history.user_id)
                if owner is None or owner.telegram_id != telegram_id:
                    raise PermissionDeniedError("Notification does not belong to this user")

            if history.acknowledged_at is not None:
                return False

            now = datetime.now(UTC)
            latency_ms = None
            if history.sent_at:
                latency_ms = (now - history.sent_at).total_seconds() * 1000

            await repo.update_history(
                history,
                status="acknowledged",
                acknowledged_at=now,
                latency_ms=latency_ms,
            )

            await logger.ainfo(
                "notification_acknowledged",
                notification_id=str(notification_id),
                user_id=str(history.user_id),
                channel=history.channel_type,
                latency_ms=latency_ms,
            )

            event = NotificationAcknowledgedEvent(
                notification_id=history.id,
                user_id=history.user_id,
                update_id=history.update_id,
                acknowledged_at=now,
            )
            await self.event_bus.publish(event)

            from app.repositories.update_repository import UpdateRepository

            update_repo = UpdateRepository(session)
            await update_repo.append_timeline_event(
                update_id=history.update_id,
                event_type="first_acknowledged",
                source="User Action",
                metadata={"user_id": str(history.user_id), "channel": history.channel_type},
            )
            await session.commit()

        return True
