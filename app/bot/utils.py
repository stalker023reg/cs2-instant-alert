"""
CS2 Instant Alert — Telegram Bot Utilities.
"""

from __future__ import annotations

from telegram import InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, TelegramError

from app.core.logging import get_logger

logger = get_logger("telegram")


async def safe_edit_message(
    query,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "MarkdownV2"
) -> bool:
    """Safely edits a message, catching 'not modified' and other Telegram errors."""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
        return True
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return True
        elif "Message to edit not found" in str(e):
            await logger.awarning("message_to_edit_not_found", user_id=query.from_user.id)
        elif "Chat not found" in str(e):
            await logger.awarning("chat_not_found", user_id=query.from_user.id)
        else:
            await logger.aerror("bad_request_edit_message", error=str(e), exc_info=True)
    except Forbidden as e:
        await logger.awarning("bot_was_blocked", user_id=query.from_user.id, error=str(e))
    except TelegramError as e:
        await logger.aerror("telegram_error_edit_message", error=str(e), exc_info=True)
    return False
