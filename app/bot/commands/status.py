"""
CS2 Instant Alert — Telegram /status Command.
"""

from __future__ import annotations

from app.core.container import Container
from app.models.user import User


async def handle_status_command(user: User, container: Container) -> tuple[str, list]:
    """Handles the /status command, returning system diagnostic info and keyboard."""

    # Gather metrics
    metrics = await container.metrics_service().get_metrics()

    # Gather Steam state
    health = await container.health_service().check_all()
    steam_status_text = "🟢 Online" if health["steam_client"] else "🔴 Offline"

    # Gather App State (CS2)
    async with container.db_manager().session() as session:
        from app.repositories.steam_state_repository import SteamStateRepository
        from app.repositories.game_repository import GameRepository
        game_repo = GameRepository(session)
        game = await game_repo.get_by_steam_app_id(730)
        state_repo = SteamStateRepository(session)
        app_state = await state_repo.get_or_create(game.id) if game else None

    # Steam client metrics
    steam_client = container.steam_client()
    last_reconnect = steam_client.reconnect_time.strftime("%Y-%m-%d %H:%M:%S UTC") if steam_client.reconnect_time else "N/A"

    uptime = metrics["uptime_seconds"]
    uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"

    last_check = "N/A"
    last_build = "N/A"
    race_mode = "⚪ Inactive"

    if app_state:
        last_check = app_state.last_check_at.strftime("%Y-%m-%d %H:%M:%S UTC") if app_state.last_check_at else "N/A"
        last_build = app_state.last_build_id or "N/A"
        race_mode = "🟢 Active" if app_state.race_mode_active else "⚪ Inactive"

    last_update = metrics["last_update"] or "N/A"

    avg_detection = "N/A" # Would require storing upstream release time to calculate
    avg_delivery = f"{metrics['avg_delivery_latency_ms']} ms" if metrics['avg_delivery_latency_ms'] else "N/A"

    text = (
        f"📊 *System Status*\n\n"
        f"*Steam:* {steam_status_text}\n"
        f"*Последняя проверка:* {last_check}\n"
        f"*Последний BuildID:* {last_build}\n"
        f"*Последнее обновление:* {last_update}\n"
        f"*Race Mode:* {race_mode}\n"
        f"*Health:* {'🟢 OK' if health['overall'] else '🔴 Issues'}\n\n"
        f"*Время работы:* {uptime_str}\n"
        f"*Найдено обновлений:* {metrics['updates_found']}\n"
        f"*Количество ошибок:* {metrics['errors']}\n\n"
        f"*Последнее переподключение Steam:* {last_reconnect}\n"
        f"*Среднее время обнаружения:* {avg_detection}\n"
        f"*Среднее время доставки:* {avg_delivery}"
    )

    # We will build an InlineKeyboardMarkup in the actual bot handler
    # For now, we return the text and a representation of the keyboard
    keyboard = [
        [{"text": "🔄 Обновить", "callback_data": "refresh_status"}]
    ]

    return text, keyboard
