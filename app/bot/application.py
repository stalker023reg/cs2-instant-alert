"""
CS2 Instant Alert — Telegram Bot Application.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CallbackContext

from app.core.container import Container
from app.core.logging import get_logger

logger = get_logger("telegram")


async def _error_handler(update: object, context: CallbackContext) -> None:
    """Глобальный обработчик ошибок бота.

    Без него python-telegram-bot пишет 'No error handlers are registered'
    и стектрейс теряется для structlog.
    """
    await logger.aerror(
        "telegram_bot_error",
        error=str(context.error),
        update=str(update) if update else None,
        exc_info=context.error,
    )


def build_application(container: Container) -> Application | None:
    """Builds and configures the python-telegram-bot Application."""
    settings = container.config()
    token = settings.telegram_bot_token.get_secret_value()
    
    if not token:
        logger.warning("Telegram bot token not provided. Bot will not start.")
        return None

    application = Application.builder().token(token).build()
    
    # Store container for dependency injection in handlers
    application.bot_data["container"] = container

    # Register handlers
    from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters
    from app.bot.handlers.menu import handle_start, handle_unknown_message
    from app.bot.handlers.router import route_callback

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CallbackQueryHandler(route_callback))

    # Add catch-all handler for any other messages/commands so the bot doesn't seem unresponsive (only in private chats)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.ALL & ~filters.COMMAND, handle_unknown_message))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.COMMAND, handle_unknown_message))

    # Глобальный error handler — без него ошибки теряются
    application.add_error_handler(_error_handler)

    return application
