"""
CS2 Instant Alert — Notification Manager.

Subscribes to Event Bus, manages user subscriptions,
and orchestrates the Dispatcher and Retry Engine.
"""

from __future__ import annotations

import asyncio

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.events.bus import EventBus
from app.events.types import UpdateDetectedEvent
from app.notifications.dispatcher import NotificationDispatcher
from app.repositories.subscription_repository import SubscriptionRepository
from app.utils.datetime import is_quiet_hours

logger = get_logger("system")


class NotificationManager:
    """
    Subscribes to events and manages the notification lifecycle.
    """

    def __init__(
        self,
        session_factory,
        event_bus: EventBus,
        dispatcher: NotificationDispatcher,
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self.settings = settings

    async def start(self) -> None:
        """Subscribe to events."""
        self.event_bus.subscribe(UpdateDetectedEvent, self.handle_update_detected)
        await logger.ainfo("notification_manager_started")

    async def handle_update_detected(self, event: UpdateDetectedEvent) -> None:
        """
        Triggered when a game update is detected.
        Finds all active subscribers and dispatches notifications.
        """
        await logger.ainfo("processing_update_event", update_id=str(event.update_id))

        async with self.session_factory() as session:
            sub_repo = SubscriptionRepository(session)
            # We need to fetch subscriptions joined with users to check quiet hours
            subscriptions = await sub_repo.get_active_subscribers(event.game_id)

            if not subscriptions:
                await logger.awarning("no_subscribers_for_game", game_id=str(event.game_id))
                return

            tasks = []
            for sub, user in subscriptions:
                # Check quiet hours (unless it's critical and user hasn't overridden it, etc.)
                # If quiet hours are enabled and we are in them, skip (or queue for later)
                # For critical updates, we might bypass quiet hours depending on user preference,
                # but currently the model only has `quiet_hours_enabled`.
                if user.quiet_hours_enabled and not event.is_critical:
                    if is_quiet_hours(user.timezone, user.quiet_hours_start, user.quiet_hours_end):
                        await logger.adebug("skipped_quiet_hours", user_id=str(user.id))
                        continue

                # For CS2 critical updates, we bypass quiet hours?
                # The requirement says "Quiet hours (DND). Flexible configuration (e.g. bypass for critical updates)".
                # Yes, if event.is_critical, we bypass.

                # Dispatch concurrently
                tasks.append(
                    self.dispatcher.dispatch_to_user(
                        user=user,
                        subscription=sub,
                        event=event,
                    )
                )

            # We execute the dispatch tasks concurrently
            # In a huge system, this would be a task queue (e.g. Celery/ARQ)
            # For 100k users, asyncio.gather with a semaphore is needed

            if tasks:
                await self._bounded_gather(tasks, concurrency_limit=100)

            await session.commit()

    async def _bounded_gather(self, tasks: list[asyncio.Task | asyncio.Future | asyncio.coroutine], concurrency_limit: int) -> None:
        """Execute tasks with a concurrency limit."""
        semaphore = asyncio.Semaphore(concurrency_limit)

        async def sem_task(task):
            async with semaphore:
                return await task

        await asyncio.gather(*(sem_task(t) for t in tasks))
