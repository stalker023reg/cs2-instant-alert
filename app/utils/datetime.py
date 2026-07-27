"""
CS2 Instant Alert — DateTime Utilities.

Timezone-aware datetime helpers used throughout the application.
"""

from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime, time


def utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def to_user_tz(dt: datetime, tz_name: str) -> datetime:
    """Convert a UTC datetime to a user's timezone."""
    user_tz = zoneinfo.ZoneInfo(tz_name)
    return dt.astimezone(user_tz)


def format_datetime(dt: datetime, tz_name: str = "UTC") -> str:
    """Format a datetime for display uniformly (e.g. 2026-06-27 21:43:15 UTC)."""
    local_dt = to_user_tz(dt, tz_name)
    tz_suffix = " UTC" if tz_name == "UTC" else ""
    return local_dt.strftime("%Y-%m-%d %H:%M:%S") + tz_suffix


def format_time_ago(dt: datetime) -> str:
    """Format a datetime as a human-readable 'time ago' string."""
    now = utc_now()
    diff = now - dt

    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{seconds}с назад"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}м назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}ч назад"
    days = hours // 24
    return f"{days}д назад"


def is_quiet_hours(
    tz_name: str,
    quiet_start: time | None,
    quiet_end: time | None,
) -> bool:
    """
    Check if current time is within user's quiet hours.

    Handles overnight ranges (e.g., 23:00 → 07:00).
    """
    if quiet_start is None or quiet_end is None:
        return False

    user_tz = zoneinfo.ZoneInfo(tz_name)
    now_local = datetime.now(user_tz).time()

    if quiet_start <= quiet_end:
        # Same-day range: e.g., 01:00 → 07:00
        return quiet_start <= now_local <= quiet_end
    else:
        # Overnight range: e.g., 23:00 → 07:00
        return now_local >= quiet_start or now_local <= quiet_end


def format_bytes(size_bytes: int | None) -> str:
    """Format bytes into human-readable size string."""
    if size_bytes is None:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
