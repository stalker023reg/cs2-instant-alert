"""
CS2 Instant Alert — Telegram Bot Main Menu Handler.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext

from app.bot.ui.keyboards import get_main_menu_keyboard
from app.bot.ui.messages import format_main_menu
from app.bot.utils import safe_edit_message
from app.core.container import Container
from app.core.logging import get_logger
from app.services.user_onboarding import ensure_user_notification_defaults
from app.utils.datetime import format_datetime

logger = get_logger("telegram")


async def _get_menu_data(container: Container) -> tuple[bool, str, str, str]:
    """Helper to fetch data needed for the main menu."""
    health = await container.health_service().check_all()
    metrics = await container.metrics_service().get_metrics()
    
    async with container.db_manager().session() as session:
        from app.repositories.game_repository import GameRepository
        from app.repositories.steam_state_repository import SteamStateRepository
        
        game_repo = GameRepository(session)
        state_repo = SteamStateRepository(session)
        
        game = await game_repo.get_by_steam_app_id(730)
        if game:
            app_state = await state_repo.get_by_game_id(game.id)
        else:
            app_state = None
            
    is_steam_online = health.get("steam_client", False)
    build_id = app_state.last_build_id if app_state and app_state.last_build_id else "N/A"
    last_check = "N/A"
    if app_state and app_state.last_check_at:
        last_check = format_datetime(app_state.last_check_at, "UTC")
    last_update = metrics.get("last_update") or "N/A"
    
    return is_steam_online, build_id, last_check, last_update


async def handle_start(update: Update, context: CallbackContext) -> None:
    """Handles the /start command. Sends the dashboard message."""
    import logging
    logging.getLogger("telegram").info(f"Received /start command! Chat ID: {update.effective_chat.id if update.effective_chat else None}")
    
    if not update.effective_chat or not update.message:
        return

    container: Container = context.application.bot_data["container"]
    chat_id = update.effective_chat.id
    if not chat_id:
        return

    # Create/Get User (which is actually a chat/group)
    async with container.db_manager().session() as session:
        from app.repositories.user_repository import UserRepository
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(chat_id)
        
        # Determine names
        title = update.effective_chat.title
        eff_user = update.effective_user
        
        username = update.effective_chat.username or (eff_user.username if eff_user else None)
        first_name = title or (eff_user.first_name if eff_user else None)
        last_name = None if title else (eff_user.last_name if eff_user else None)

        if not user:
            from app.models.user import User
            user = User(
                telegram_id=chat_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            await user_repo.create(user)

        user.username = username
        user.first_name = first_name
        user.last_name = last_name

        # Создаём подписку и канал доставки. Если что-то пойдёт не так —
        # пользователь всё равно сохранится и увидит меню.
        try:
            await ensure_user_notification_defaults(session, user, container.config())
        except Exception as e:
            await logger.aerror(
                "user_onboarding_failed",
                chat_id=chat_id,
                error=str(e),
                exc_info=True,
            )

        await session.commit()
            
        if not user.is_admin:
            # Simple text for normal users
            text = "✅ Вы успешно подписаны на уведомления об обновлениях CS2. Бот будет автоматически присылать информацию о новых патчах."
            await update.message.reply_text(text)
            return

        # Dashboard for admins
        is_steam_online, build_id, last_check, last_update = await _get_menu_data(container)
        text = format_main_menu(is_steam_online, build_id, last_check, last_update)
        keyboard = get_main_menu_keyboard(is_admin=user.is_admin)

        # Try to delete the old dashboard message to keep chat clean
        last_msg_id = user.settings.get("last_status_message_id") if isinstance(user.settings, dict) else None
        if last_msg_id:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=last_msg_id
                )
            except Exception:
                pass
                
        msg = await update.message.reply_text(
            text, 
            reply_markup=keyboard, 
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        if not isinstance(user.settings, dict):
            user.settings = {}
        user.settings["last_status_message_id"] = msg.message_id
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(user, "settings")
            
        await session.commit()



async def show_main_menu(update: Update, context: CallbackContext) -> None:
    """Handles the 'menu' callback. Updates the existing message."""
    query = update.callback_query
    if not query:
        return

    container: Container = context.application.bot_data["container"]
    user_id = update.effective_user.id if update.effective_user else None
    
    is_admin = False
    if user_id:
        async with container.db_manager().session() as session:
            from app.repositories.user_repository import UserRepository
            user_repo = UserRepository(session)
            user = await user_repo.get_by_telegram_id(user_id)
            if user:
                is_admin = user.is_admin

    is_steam_online, build_id, last_check, last_update = await _get_menu_data(container)
    text = format_main_menu(is_steam_online, build_id, last_check, last_update)
    keyboard = get_main_menu_keyboard(is_admin=is_admin)

    await safe_edit_message(query, text, keyboard)


async def handle_unknown_message(update: Update, context: CallbackContext) -> None:
    """Silently ignore any unknown messages. The bot only reacts to /start and inline buttons."""
    return
