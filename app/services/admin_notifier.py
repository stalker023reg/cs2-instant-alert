"""
CS2 Instant Alert — Admin Notifier Service.

Sends system and broadcast messages to application administrators.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.models.user import User
from app.notifications.channels.telegram import TelegramChannel

logger = get_logger("system")


class AdminNotifierService:
    """Broadcasts messages to administrators."""

    def __init__(
        self,
        session_factory,
        telegram_channel: TelegramChannel,
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.telegram = telegram_channel
        self.settings = settings

    async def broadcast(self, message: str) -> None:
        """Sends a message to all admin users."""
        if not self.telegram.bot:
            await logger.awarning("admin_broadcast_skipped_no_bot_token")
            return

        async with self.session_factory() as session:
            # 1. Find all users with is_admin == True
            stmt = select(User).where(User.is_admin == True, User.is_active == True)
            result = await session.execute(stmt)
            admin_users = result.scalars().all()

            import asyncio

            from telegram.constants import ParseMode

            sent_count = 0

            # 2. Send to admins
            if admin_users:
                for admin in admin_users:
                    try:
                        await self.telegram.bot.send_message(
                            chat_id=admin.telegram_id,
                            text=message,
                            parse_mode=ParseMode.HTML, # Using HTML for simple bolding, or adjust text if using MarkdownV2
                        )
                        sent_count += 1
                        await asyncio.sleep(0.05) # Rate limit safety
                    except Exception as e:
                        await logger.aerror("admin_broadcast_failed", admin_id=admin.telegram_id, error=str(e))

            # 3. Fallback if no admins found in DB
            if not admin_users and self.settings.admin_telegram_id:
                try:
                    await self.telegram.bot.send_message(
                        chat_id=self.settings.admin_telegram_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                    )
                    sent_count += 1
                except Exception as e:
                    await logger.aerror("admin_broadcast_fallback_failed", error=str(e))

        await logger.adebug("admin_broadcast_completed", sent_count=sent_count)
