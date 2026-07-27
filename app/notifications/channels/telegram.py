"""
CS2 Instant Alert — Telegram Notification Channel.

Delivers messages using python-telegram-bot.
"""

from __future__ import annotations

import uuid

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.events.types import UpdateDetectedEvent
from app.models.notification_channel import NotificationChannel
from app.models.user import User
from app.notifications.base import AbstractNotificationChannel, ChannelDeliveryError
from app.notifications.formatter import TelegramFormatter

logger = get_logger("telegram")


class TelegramChannel(AbstractNotificationChannel):
    """Delivers alerts via Telegram."""

    def __init__(self, settings: AppSettings) -> None:
        token = settings.telegram_bot_token.get_secret_value()
        self.bot = Bot(token=token) if token else None

    @property
    def channel_type(self) -> str:
        return "telegram"

    async def send_update_alert(
        self,
        user: User,
        channel_config: NotificationChannel,
        event: UpdateDetectedEvent,
        notification_id: uuid.UUID,
    ) -> str | None:
        if not self.bot:
            raise ChannelDeliveryError("Telegram bot token not configured", code="TG_NO_TOKEN")

        text = TelegramFormatter.format_update_alert(
            event=event,
            timezone=user.timezone,
            language=user.language,
        )

        # Acknowledgement button removed
        reply_markup = None

        import asyncio

        from telegram.error import RetryAfter

        max_retries = 3
        for attempt in range(max_retries):
            try:
                msg = await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
                
                # Pin message if enabled
                if isinstance(user.settings, dict) and user.settings.get("auto_pin_updates", False):
                    try:
                        await self.bot.pin_chat_message(
                            chat_id=user.telegram_id,
                            message_id=msg.message_id,
                            disable_notification=True
                        )
                    except Exception as pin_err:
                        await logger.awarning("telegram_pin_failed", error=str(pin_err))
                        
                return str(msg.message_id)
            except RetryAfter as e:
                await logger.awarning("telegram_rate_limit", retry_after=e.retry_after, attempt=attempt+1)
                if attempt < max_retries - 1:
                    await asyncio.sleep(e.retry_after)
                else:
                    raise ChannelDeliveryError(f"Telegram rate limit exceeded: {e}", code="TG_RATE_LIMIT") from e
            except TelegramError as e:
                raise ChannelDeliveryError(f"Telegram delivery failed: {e}", code="TG_DELIVERY_FAIL") from e

    async def edit_update_alert(
        self,
        user: User,
        message_id: str,
        event: UpdateDetectedEvent,
        patch_notes_html: str | None = None,
        patch_url: str | None = None,
    ) -> None:
        """Edit an existing message, replacing placeholder with patch notes."""
        if not self.bot:
            return

        text = TelegramFormatter.format_update_alert(
            event=event,
            timezone=user.timezone,
            language=user.language,
            patch_notes_html=patch_notes_html,
            patch_url=patch_url,
        )

        try:
            await self.bot.edit_message_text(
                chat_id=user.telegram_id,
                message_id=int(message_id),
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError as e:
            await logger.awarning("telegram_edit_failed", error=str(e), message_id=message_id)
