"""
CS2 Instant Alert — Telegram Bot Admin Handler.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext

from app.bot.ui.keyboards import get_admin_keyboard, get_back_to_admin_keyboard
from app.bot.ui.messages import format_admin_events
from app.bot.utils import safe_edit_message
from app.core.container import Container
from app.core.logging import get_logger
from app.utils.formatting import escape_markdown_v2

logger = get_logger("telegram")


async def handle_admin(update: Update, context: CallbackContext) -> None:
    """Handles the admin screen and its actions."""
    query = update.callback_query
    if not query or not query.data:
        return

    container: Container = context.application.bot_data["container"]
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    # Check admin privileges
    async with container.db_manager().session() as session:
        from app.repositories.user_repository import UserRepository
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(user_id)
        if not user or not user.is_admin:
            await query.answer("У вас нет прав доступа.", show_alert=True)
            return

    action = query.data.split(":")[-1]

    if action == "admin":
        text = "🛠 *Панель Администратора*\n\nВыберите действие:"
        keyboard = get_admin_keyboard()
        await safe_edit_message(query, escape_markdown_v2(text), keyboard)

    elif action == "logs":
        await safe_edit_message(query, escape_markdown_v2("⏳ Загружаю последние события..."))

        events = []
        async with container.db_manager().session() as session:
            from sqlalchemy import select
            from app.models.update import Update as UpdateModel
            
            stmt = select(UpdateModel.timeline).order_by(UpdateModel.detected_at.desc()).limit(1)
            latest_timeline = await session.scalar(stmt)
            if latest_timeline:
                # Get last 20 events from the timeline
                timeline_events = latest_timeline.get("events", [])
                events = [
                    f"[{e.get('timestamp', 'N/A')}] {e.get('type', 'unknown')}"
                    for e in timeline_events[-20:]
                ]

        text = format_admin_events(events)
        keyboard = get_back_to_admin_keyboard()
        await safe_edit_message(query, text, keyboard)

    elif action == "test":
        from app.bot.handlers.test_notify import handle_test
        await handle_test(update, context)
