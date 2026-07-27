"""
CS2 Instant Alert — Notification Dispatcher.

Handles fan-out delivery of notifications to user-configured channels.
Supports falling back to lower-priority channels if primary fails.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.types import UpdateDetectedEvent
from app.models.notification_history import NotificationHistory
from app.models.subscription import Subscription
from app.models.user import User
from app.notifications.base import AbstractNotificationChannel, ChannelDeliveryError
from app.repositories.notification_repository import NotificationRepository

logger = get_logger("system")


class NotificationDispatcher:
    """
    Dispatches events to a user's configured channels.
    """

    def __init__(
        self,
        channels: dict[str, AbstractNotificationChannel],
        session_factory,
    ) -> None:
        self.channels = channels
        self.session_factory = session_factory

    async def dispatch_to_user(
        self,
        user: User,
        subscription: Subscription,
        event: UpdateDetectedEvent,
    ) -> None:
        """
        Deliver an update to a user through their configured channels.
        
        Fetches the user's active channels, orders them by priority.
        Attempts delivery sequentially. If a channel fails and the event
        is critical, it immediately escalates to the next channel.
        """
        # Each concurrent delivery gets its own SQLAlchemy session. Sharing one
        # session from a singleton dispatcher is unsafe and can corrupt transaction
        # state when multiple users are notified at once.
        async with self.session_factory() as session:
            history_repo = NotificationRepository(session)
            user_channels = await history_repo.get_active_channels_for_user(user.id)

            if not user_channels:
                await logger.awarning("user_has_no_channels", user_id=str(user.id))
                return

            for channel_config in user_channels:
                channel = self.channels.get(channel_config.channel_type)
                if not channel:
                    await logger.aerror("unsupported_channel_type", channel_type=channel_config.channel_type)
                    continue

                success = await self._send_to_channel(
                    session=session,
                    history_repo=history_repo,
                    channel=channel,
                    channel_config=channel_config,
                    user=user,
                    event=event,
                )

                if success:
                    # Successfully delivered, no need to escalate
                    break

                if not event.is_critical:
                    break

    async def _send_to_channel(
        self,
        session: AsyncSession,
        history_repo: NotificationRepository,
        channel: AbstractNotificationChannel,
        channel_config,
        user: User,
        event: UpdateDetectedEvent,
    ) -> bool:
        """Returns True if successfully delivered, False otherwise."""
        from sqlalchemy.exc import IntegrityError

        notification_id = uuid.uuid4()

        # Record attempt in history
        history = NotificationHistory(
            id=notification_id,
            user_id=user.id,
            update_id=event.update_id,
            channel_type=channel.channel_type,
            status="pending",
            retry_count=0,
        )

        try:
            await history_repo.create_history(history)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await logger.adebug("duplicate_notification_skipped", user_id=str(user.id), update_id=str(event.update_id))
            return True # Pretend it succeeded so we don't escalate

        # Attempt delivery
        try:
            provider_message_id = await channel.send_update_alert(
                user=user,
                channel_config=channel_config,
                event=event,
                notification_id=notification_id,
            )

            # Mark success
            await history_repo.update_history(
                history,
                status="delivered",
                sent_at=event.detected_at, # Approximate, to be exact we could use datetime.now(timezone.utc)
                provider_message_id=provider_message_id,
                message_id=provider_message_id,
                chat_id=str(user.telegram_id) if channel.channel_type == "telegram" else None,
            )
            await session.commit()

            await logger.ainfo(
                "notification_delivered",
                user_id=str(user.id),
                channel=channel.channel_type,
                update_id=str(event.update_id),
            )

            if event.is_critical:
                await logger.ainfo("CriticalNotificationSent", user_id=str(user.id), channel=channel.channel_type)

            from app.repositories.update_repository import UpdateRepository
            update_repo = UpdateRepository(session)
            await update_repo.append_timeline_event(
                update_id=event.update_id,
                event_type="notification_sent",
                source=channel.channel_type,
                metadata={"user_id": str(user.id), "notification_id": str(notification_id)}
            )
            await session.commit()

            return True

        except ChannelDeliveryError as e:
            # Mark failed
            await history_repo.update_history(
                history,
                status="failed",
                error_message=str(e),
            )
            await session.commit()
            await logger.awarning(
                "notification_failed",
                user_id=str(user.id),
                channel=channel.channel_type,
                error=str(e),
            )
            return False
        except Exception as e:
            # Unexpected provider bugs must not leave a permanently "pending"
            # history row or abort delivery for every other subscriber.
            await history_repo.update_history(
                history,
                status="failed",
                error_message=f"Unexpected delivery error: {e}",
            )
            await session.commit()
            await logger.aerror(
                "notification_delivery_crashed",
                user_id=str(user.id),
                channel=channel.channel_type,
                error=str(e),
                exc_info=True,
            )
            return False
