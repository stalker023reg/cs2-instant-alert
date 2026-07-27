"""Create the default CS2 subscription and Telegram delivery channel."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppSettings
from app.models.notification_channel import NotificationChannel
from app.models.user import User
from app.repositories.game_repository import GameRepository
from app.repositories.notification_repository import NotificationChannelRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository


async def ensure_user_notification_defaults(
    session: AsyncSession,
    user: User,
    settings: AppSettings,
) -> bool:
    """Ensure a Telegram user can actually receive CS2 alerts."""
    game = await GameRepository(session).get_by_steam_app_id(730)
    if game is None:
        return False

    user_settings = user.settings if isinstance(user.settings, dict) else {}
    critical_enabled = bool(user_settings.get("critical_notifications_enabled", True))
    retry_interval = int(user_settings.get("retry_interval_seconds", 300))

    subscription_repo = SubscriptionRepository(session)
    subscription = await subscription_repo.subscribe(
        user_id=user.id,
        game_id=game.id,
        critical_enabled=critical_enabled,
    )
    subscription.is_active = True
    subscription.critical_enabled = critical_enabled
    subscription.repeat_enabled = critical_enabled
    subscription.repeat_interval_seconds = max(60, retry_interval)

    channel_repo = NotificationChannelRepository(session)
    channel = await channel_repo.get_user_channel_by_type(user.id, "telegram")
    if channel is None:
        channel = NotificationChannel(
            user_id=user.id,
            channel_type="telegram",
            config={},
            is_active=True,
            priority=0,
        )
        await channel_repo.create(channel)
    else:
        channel.is_active = True
        channel.priority = 0

    user.is_active = True
    if user.telegram_id in settings.telegram_admin_ids:
        user.is_admin = True
    return True


async def backfill_existing_user_defaults(
    session: AsyncSession,
    settings: AppSettings,
) -> int:
    """Repair users created by older versions that omitted subscriptions."""
    users = await UserRepository(session).get_active_users()
    repaired = 0
    for user in users:
        if await ensure_user_notification_defaults(session, user, settings):
            repaired += 1
    return repaired
