"""
CS2 Instant Alert — Notification Formatter.

Generates clean, player-focused message payloads for Telegram.
"""

from __future__ import annotations

from app.events.types import UpdateDetectedEvent
from app.utils.datetime import format_datetime
from app.utils.formatting import code_html


class TelegramFormatter:
    """Formats events into Telegram HTML strings."""

    @staticmethod
    def format_update_alert(
        event: UpdateDetectedEvent,
        timezone: str,
        language: str = "ru",
        patch_notes_html: str | None = None,
        patch_url: str | None = None,
        ai_analyzed: bool = False,
        depot_diff_html: str | None = None,
        patch_version: str | None = None,
        status_text: str | None = None,
        is_timeout: bool = False,
    ) -> str:
        """
        Format an UpdateDetectedEvent for Telegram.

        Stage 1: instant alert with placeholder.
        Stage 2: edited alert with datamining / patch notes.
        """
        title = "🆕 <b>Обновление CS2</b>"

        lines = [
            title,
            "",
            f"🕐 {code_html(format_datetime(event.detected_at, timezone))}",
            f"🔢 Build: {code_html(event.build_id)}",
        ]

        if patch_version:
            lines.append(f"🏷 Версия: {code_html(patch_version)}")

        if event.previous_build_id:
            lines.append(f"⏮ Прошлый: {code_html(event.previous_build_id)}")

        # Depots section (only client components)
        if depot_diff_html:
            lines.append("")
            lines.append(f"{'─' * 22}")
            lines.append("📦 <b>Изменённые компоненты</b>")
            lines.append("")
            lines.append(depot_diff_html)

        # Stage 2: Patch notes / AI analysis / Datamining OR Stage 1 Placeholder
        lines.append("")
        lines.append(f"{'─' * 22}")

        if patch_notes_html:
            if ai_analyzed:
                header = "🤖 <b>Разбор обновления (AI + Датамайнинг)</b>"
                lines.append(header)
            else:
                lines.append("📋 <b>Patch Notes</b>")
            lines.append("")
            lines.append(patch_notes_html)

            if patch_url:
                lines.append("")
                lines.append(f'🔗 <a href="{patch_url}">Читать полностью на Steam</a>')
        elif is_timeout:
            lines.append("ℹ️ <i>Техническое обновление без публичного списка изменений.</i>")
        else:
            lines.append("⏳ <i>Анализируем файлы обновления и ждем распаковку дампа... (обычно занимает 3–10 минут)</i>")

        return "\n".join(lines)
