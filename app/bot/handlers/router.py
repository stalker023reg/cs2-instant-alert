"""
CS2 Instant Alert — Telegram Bot Callback Router.
"""

from __future__ import annotations

import uuid

from telegram import Update
from telegram.ext import CallbackContext

from app.core.container import Container
from app.core.logging import get_logger

logger = get_logger("telegram")


async def route_callback(update: Update, context: CallbackContext) -> None:
    """Central router for all CallbackQueries."""
    query = update.callback_query
    if not query or not query.data:
        return

    # Acknowledge the callback immediately to stop the loading spinner on the button
    await query.answer()

    data = query.data
    container: Container = context.application.bot_data["container"]
    telegram_id = update.effective_user.id if update.effective_user else None

    # Fetch user to check admin rights
    is_admin = False
    if telegram_id:
        async with container.db_manager().session() as session:
            from app.repositories.user_repository import UserRepository
            user_repo = UserRepository(session)
            user = await user_repo.get_by_telegram_id(telegram_id)
            if user:
                is_admin = user.is_admin

    try:
        # Check permissions for admin-only menus
        if data in ["menu", "status", "admin"] or data.startswith("status:") or data.startswith("admin:"):
            if not is_admin:
                await query.edit_message_text(
                    "❌ Данное действие недоступно."
                )
                return

        if data == "menu":
            from app.bot.handlers.menu import show_main_menu
            await show_main_menu(update, context)
            
        elif data.startswith("status"):
            from app.bot.handlers.status import handle_status
            await handle_status(update, context)

        elif data.startswith("ack_"):
            notification_id = uuid.UUID(data.removeprefix("ack_"))
            acknowledged = await container.acknowledgement_service().acknowledge(
                notification_id,
                telegram_id=telegram_id,
            )
            if acknowledged:
                await query.edit_message_reply_markup(reply_markup=None)
            else:
                await logger.adebug(
                    "notification_already_acknowledged",
                    notification_id=str(notification_id),
                )
            
        elif data.startswith("admin"):
            from app.bot.handlers.admin import handle_admin
            await handle_admin(update, context)
            
        elif data == "none":
            # Just a decorative button
            pass
            
        else:
            await logger.awarning("unknown_callback_data", data=data)
            
    except Exception as e:
        await logger.aerror("callback_routing_error", error=str(e), exc_info=True)
        try:
            await query.edit_message_text(
                "❌ Произошла ошибка при выполнении операции.\nПопробуйте позже."
            )
        except Exception:
            pass
