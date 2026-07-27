"""
CS2 Instant Alert — Notification Formatter.

Generates localized, channel-specific message payloads from events.
Currently focuses on Telegram HTML formatting.
"""

from __future__ import annotations

from app.events.types import UpdateDetectedEvent
from app.utils.datetime import format_bytes, format_datetime
from app.utils.formatting import bold_html, code_html


class TelegramFormatter:
    """Formats events into Telegram HTML strings."""

    @staticmethod
    def format_update_alert(
        event: UpdateDetectedEvent,
        timezone: str,
        language: str = "ru",
        patch_notes_html: str | None = None,
        patch_url: str | None = None,
    ) -> str:
        """Format an UpdateDetectedEvent for Telegram."""

        title = "🚨 <b>ВЫШЛО ОБНОВЛЕНИЕ CS2</b> 🚨" if event.is_critical else "🆕 <b>Обновление CS2</b>"

        lines = [
            title,
            "",
            f"🕐 {code_html(format_datetime(event.detected_at, timezone))}",
            f"🔢 Build: {code_html(event.build_id)}",
        ]

        if event.previous_build_id:
            lines.append(f"⏮ Прошлый: {code_html(event.previous_build_id)}")

        if patch_notes_html:
            lines.append("")
            lines.append(f"{'─' * 22}")
            lines.append(f"📋 <b>Patch Notes</b>")
            lines.append("")
            lines.append(patch_notes_html)

            if patch_url:
                lines.append("")
                lines.append(f'🔗 <a href="{patch_url}">Читать полностью на Steam</a>')
        else:
            lines.append("")
            lines.append("<i>⏳ Ждём patch notes...</i>")

        return "\n".join(lines)

