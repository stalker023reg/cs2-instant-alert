"""
CS2 Instant Alert — Telegram Bot Status Handler.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext

from app.bot.ui.keyboards import get_status_keyboard
from app.bot.ui.messages import format_status
from app.bot.utils import safe_edit_message
from app.core.container import Container
from app.core.logging import get_logger
from app.utils.datetime import format_datetime
from app.utils.formatting import escape_markdown_v2

logger = get_logger("telegram")


async def handle_status(update: Update, context: CallbackContext) -> None:
    """Handles the status screen and its refresh button."""
    query = update.callback_query
    if not query:
        return

    container: Container = context.application.bot_data["container"]

    # Show loading indicator if requested a refresh
    if query.data == "status:refresh":
        await safe_edit_message(query, escape_markdown_v2("⏳ Загружаю данные статуса..."))

    metrics = await container.metrics_service().get_metrics()
    health = await container.health_service().check_all()
    steam_status_text = "🟢 Online" if health.get("steam_client") else "🔴 Offline"

    async with container.db_manager().session() as session:
        from app.repositories.game_repository import GameRepository
        from app.repositories.steam_state_repository import SteamStateRepository
        
        game_repo = GameRepository(session)
        state_repo = SteamStateRepository(session)
        
        game = await game_repo.get_by_steam_app_id(730)
        app_state = await state_repo.get_by_game_id(game.id) if game else None

    uptime = metrics.get("uptime_seconds", 0)
    uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"

    last_check = "N/A"
    last_build = "N/A"
    race_mode = "⚪ Inactive"

    if app_state:
        if app_state.last_check_at:
            last_check = format_datetime(app_state.last_check_at, "UTC")
        last_build = app_state.last_build_id or "N/A"
        race_mode = "🟢 Active" if app_state.race_mode_active else "⚪ Inactive"
        if app_state.last_update_at:
            last_update = format_datetime(app_state.last_update_at, "UTC")
        else:
            last_update = metrics.get("last_update") or "N/A"
    else:
        last_update = metrics.get("last_update") or "N/A"
    health_str = "🟢 OK" if health.get("overall") else "🔴 Issues"

    text = format_status(
        version=container.config().version,
        steam_status_text=steam_status_text,
        last_check=last_check,
        last_build=last_build,
        last_update=last_update,
        race_mode=race_mode,
        health_str=health_str,
        uptime_str=uptime_str,
        updates_found=metrics.get("updates_found", 0),
        errors=metrics.get("errors", 0)
    )
    keyboard = get_status_keyboard()

    await safe_edit_message(query, text, keyboard)
