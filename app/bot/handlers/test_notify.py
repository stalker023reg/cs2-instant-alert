"""
CS2 Instant Alert — Telegram Bot Test Notification Handler.
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC

from telegram import Update
from telegram.ext import CallbackContext

from app.core.container import Container
from app.core.logging import get_logger
logger = get_logger("telegram")


async def handle_test(update: Update, context: CallbackContext) -> None:
    """Handles the test notification action."""
    query = update.callback_query
    if not query:
        return

    container: Container = context.application.bot_data["container"]
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    # Check if the user exists
    async with container.db_manager().session() as session:
        from app.repositories.user_repository import UserRepository
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(user_id)
        if not user:
            await query.answer("Вы не зарегистрированы.", show_alert=True)
            return
        if not user.is_admin:
            await query.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        all_active_users = await user_repo.get_active_users()

    try:
        await query.edit_message_text("⏳ Запускаю тестовое уведомление для всех...")
    except Exception:
        pass

    mock_update_id = uuid.uuid4()
    
    # Send mock message
    try:
        from app.notifications.formatter import TelegramFormatter
        from app.events.types import UpdateDetectedEvent
        from app.steam.types import AppUpdateData, BranchInfo, SteamSource

        checked_at = datetime.now(UTC)
        raw_data = AppUpdateData(
            app_id=730,
            source=SteamSource.PICS,
            checked_at=checked_at,
            branches={
                "public": BranchInfo(name="public", build_id="1234567_TEST")
            },
        )
        
        event = UpdateDetectedEvent(
            update_id=mock_update_id,
            game_id=uuid.UUID("00000000-0000-0000-0000-000000000730"),
            build_id="1234567_TEST",
            previous_build_id="1234566_TEST",
            detected_at=checked_at,
            is_critical=True,
            raw_data=raw_data,
        )
        
        banner_url = getattr(container.config, "banner_image_url", "https://cs2-instant-alert.fly.dev/static/banner.jpg")

        from telegram import LinkPreviewOptions
        link_preview = (
            LinkPreviewOptions(url=banner_url, prefer_large_media=True, show_above_text=True)
            if banner_url
            else LinkPreviewOptions(is_disabled=True)
        )

        for u in all_active_users:
            u_lang = u.language or "ru"
            u_is_en = u_lang.lower().startswith("en")
            user_text = TelegramFormatter.format_update_alert(
                event=event,
                timezone=u.timezone or "UTC",
                language=u_lang,
                banner_url=banner_url,
            )
            user_text += "\n\n<i>This is a GLOBAL test notification.</i>" if u_is_en else "\n\n<i>Это ГЛОБАЛЬНОЕ тестовое уведомление.</i>"

            try:
                await context.bot.send_message(
                    chat_id=u.telegram_id,
                    text=user_text,
                    parse_mode="HTML",
                    link_preview_options=link_preview,
                )
            except Exception as e:
                await logger.awarning("test_notification_failed_for_user", telegram_id=u.telegram_id, error=str(e))
        
        # Restore menu
        from app.bot.handlers.menu import show_main_menu
        await show_main_menu(update, context)
        
    except Exception as e:
        await logger.aerror("test_notification_failed", error=str(e), exc_info=True)
        try:
            await query.edit_message_text("❌ Ошибка отправки тестового уведомления.")
        except Exception:
            pass
