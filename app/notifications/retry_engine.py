"""
CS2 Instant Alert — Notification Retry Engine.

Handles escalating retries for critical notifications that have
not been acknowledged by the user.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.notifications.base import AbstractNotificationChannel, ChannelDeliveryError
from app.repositories.notification_repository import NotificationRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository

logger = get_logger("system")


class RetryEngine:
    """
    Background worker that re-sends unacknowledged notifications based on
    the user's retry settings and critical mode.
    """

    def __init__(
        self,
        session_factory,
        channels: dict[str, AbstractNotificationChannel],
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.channels = channels
        self.settings = settings
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the retry loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="RetryEngine")
        await logger.ainfo("retry_engine_started")

    async def stop(self) -> None:
        """Stop the retry loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        """Periodic loop to check for unacknowledged notifications."""
        try:
            while self._running:
                await self._process_retries()
                await asyncio.sleep(30) # Check every 30 seconds
        except asyncio.CancelledError:
            await logger.ainfo("retry_engine_stopped")
        except Exception as e:
            await logger.aerror("retry_engine_crashed", error=str(e), exc_info=True)
            if self._running:
                await asyncio.sleep(60)
                self._task = asyncio.create_task(self._loop(), name="RetryEngine")

    async def _process_retries(self) -> None:
        """Find pending retries and dispatch them."""
        # Retries disabled per user request
        return
        now = datetime.now(UTC)

        async with self.session_factory() as session:
            notif_repo = NotificationRepository(session)
            sub_repo = SubscriptionRepository(session)
            user_repo = UserRepository(session)

            # Fetch all delivered but unacknowledged notifications
            unacked = await notif_repo.history_repo.get_unacknowledged_critical()

            for history in unacked:
                if not history.sent_at:
                    continue

                # We need user and subscription to know retry policy
                user = await user_repo.get_by_id(history.user_id)
                # To get subscription, we need the game_id from the update.
                # This is an extra query, but let's assume we can fetch it.
                # Since we want to be efficient, let's load the update relationship.
                await session.refresh(history, ["update"])

                sub = await sub_repo.get_by_user_and_game(history.user_id, history.update.game_id)
                if not user or not sub or not sub.repeat_enabled:
                    continue

                interval_seconds = sub.repeat_interval_seconds
                max_retries = 3
                if sub.critical_enabled:
                    max_retries = 999  # Infinite

                if history.retry_count >= max_retries:
                    if history.status != "failed":
                        await notif_repo.update_history(history, status="failed")
                        await logger.ainfo("RetryStopped", notification_id=str(history.id), reason="max_retries_exceeded")
                        await session.commit()
                    continue

                # Calculate if it's time to retry
                time_since_sent = (now - history.sent_at).total_seconds()
                # Exponential backoff or fixed interval? User requested settings interval.
                # We use fixed interval * (retry_count + 1) to spread them out?
                # Actually, standard fixed interval.
                required_interval = interval_seconds

                if time_since_sent > required_interval:
                    # Time to retry!
                    channel = self.channels.get(history.channel_type)
                    if not channel:
                        continue

                    # Fetch channel config
                    channel_config = await notif_repo.channel_repo.get_user_channel_by_type(user.id, channel.channel_type)
                    if not channel_config:
                        continue

                    try:
                        # Re-create the event from raw_data inside update if needed,
                        # but AbstractNotificationChannel needs UpdateDetectedEvent.
                        # We can construct a dummy event or pass necessary fields.
                        from app.events.types import UpdateDetectedEvent
                        from app.steam.types import AppUpdateData

                        raw_data = history.update.raw_data
                        # In real life we'd reconstruct AppUpdateData.
                        # For now we'll do our best.
                        event = UpdateDetectedEvent(
                            update_id=history.update_id,
                            game_id=history.update.game_id,
                            build_id=history.update.build_id,
                            previous_build_id=history.update.previous_build_id,
                            is_critical=sub.critical_enabled,
                            detected_at=history.update.detected_at,
                            raw_data=AppUpdateData(**raw_data) if raw_data else AppUpdateData(app_id=0, source="pics", checked_at=now)
                        )

                        await channel.send_update_alert(
                            user=user,
                            channel_config=channel_config,
                            event=event,
                            notification_id=history.id,
                        )

                        # Update history
                        await notif_repo.update_history(
                            history,
                            retry_count=history.retry_count + 1,
                            sent_at=now,  # Reset sent_at to now so next retry is based on this
                        )

                        await logger.ainfo("RetryStarted", notification_id=str(history.id))

                        await logger.ainfo(
                            "notification_retried",
                            notification_id=str(history.id),
                            user_id=str(user.id),
                            retry_count=history.retry_count + 1,
                        )
                    except ChannelDeliveryError as e:
                        await logger.awarning(
                            "notification_retry_failed",
                            notification_id=str(history.id),
                            error=str(e),
                        )

            await session.commit()
