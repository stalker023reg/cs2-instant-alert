"""
CS2 Instant Alert — Telegram Bot Messages (UI).
"""

from __future__ import annotations

from app.utils.formatting import escape_markdown_v2, bold, code


def format_main_menu(
    is_steam_online: bool,
    build_id: str,
    last_check: str,
    last_update: str
) -> str:
    """Formats the compact main menu text."""
    steam_status = "🟢 Online" if is_steam_online else "🔴 Offline"
    
    return (
        f"🏠 {bold('CS2 Instant Alert')}\n\n"
        f"Steam: {escape_markdown_v2(steam_status)}\n"
        f"BuildID: {code(build_id)}\n"
        f"Последняя проверка: {code(last_check)}\n"
        f"Последнее обновление: {code(last_update)}\n\n"
        f"{escape_markdown_v2('Выберите действие ниже:')}"
    )


def format_status(
    version: str,
    steam_status_text: str,
    last_check: str,
    last_build: str,
    last_update: str,
    race_mode: str,
    health_str: str,
    uptime_str: str,
    updates_found: int,
    errors: int
) -> str:
    """Formats the detailed status screen."""
    return (
        f"📊 {bold('Системный Статус')} `v{escape_markdown_v2(version)}`\n\n"
        f"{bold('Steam:')} {escape_markdown_v2(steam_status_text)}\n"
        f"{bold('Последняя проверка:')} {code(last_check)}\n"
        f"{bold('Последний BuildID:')} {code(last_build)}\n"
        f"{bold('Последнее обновление:')} {code(last_update)}\n"
        f"{bold('Race Mode:')} {escape_markdown_v2(race_mode)}\n"
        f"{bold('Health:')} {escape_markdown_v2(health_str)}\n\n"
        f"{bold('Время работы:')} {code(uptime_str)}\n"
        f"{bold('Найдено обновлений:')} {escape_markdown_v2(str(updates_found))}\n"
        f"{bold('Количество ошибок:')} {escape_markdown_v2(str(errors))}\n"
    )


def format_admin_events(events: list[str]) -> str:
    """Formats a list of recent events for the admin screen."""
    text = f"📋 {bold('Последние события')}\n\n"
    if not events:
        text += escape_markdown_v2("Нет событий.")
    else:
        for event in events:
            text += f"• {escape_markdown_v2(event)}\n"
    return text

