"""
CS2 Instant Alert — Telegram /test Command.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.container import Container
from app.events.types import UpdateDetectedEvent
from app.models.update import Update
from app.models.user import User


async def handle_test_command(user: User, container: Container) -> str:
    """
    Handles the /test command.
    Fakes a critical update to test the entire delivery pipeline for this user,
    including the Dispatcher, Pushover fallback (if configured), and RetryEngine.
    """
    mock_update_id = uuid.uuid4()

    # 1. Create a mock Update in DB so Foreign Keys in NotificationHistory work.
    async with container.db_manager().session() as session:
        mock_update = Update(
            id=mock_update_id,
            game_id=730,
            build_id="TEST_BUILD_" + str(mock_update_id)[:8],
            previous_build_id="OLD_BUILD",
            is_critical=True,
            detected_at=datetime.now(UTC),
            raw_data={"is_test": True}
        )
        session.add(mock_update)
        await session.commit()

        # Need to fetch the user's subscription to CS2
        from app.repositories.subscription_repository import SubscriptionRepository
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_user_and_game(user.id, 730)
        if not sub:
            return "❌ У вас нет подписки на CS2. Сначала включите уведомления."

    # 2. Construct the mock event
    from app.steam.types import AppUpdateData
    event = UpdateDetectedEvent(
        update_id=mock_update_id,
        game_id=730,
        build_id=mock_update.build_id,
        previous_build_id="OLD_BUILD",
        is_critical=True,
        detected_at=mock_update.detected_at,
        raw_data=AppUpdateData(app_id=730, source="pics", checked_at=mock_update.detected_at)
    )

    # 3. Dispatch only to this user
    # We bypass NotificationManager (which dispatches to everyone)
    # and call the Dispatcher directly.
    dispatcher = container.notification_dispatcher()
    await dispatcher.dispatch_to_user(
        user=user,
        subscription=sub,
        event=event,
    )

    return "✅ Тестовое уведомление отправлено! (Проверьте каналы и RetryEngine)"
