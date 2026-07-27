"""
CS2 Instant Alert — Telegram Bot Keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup | None:
    """Returns the main menu keyboard. Only available for admins."""
    if not is_admin:
        return None
        
    keyboard = [
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("🧪 Проверить уведомления", callback_data="admin:test")],
        [InlineKeyboardButton("🛠 Администрирование", callback_data="admin")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_status_keyboard() -> InlineKeyboardMarkup:
    """Returns the status screen keyboard."""
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="status:refresh")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Returns the admin screen keyboard."""
    keyboard = [
        [InlineKeyboardButton("📋 Последние события", callback_data="admin:logs")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_to_admin_keyboard() -> InlineKeyboardMarkup:
    """Returns a simple back to admin keyboard."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin")]])
