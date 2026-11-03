"""
CS2 Instant Alert — Notification Formatter.

Generates clean, player-focused message payloads for Telegram.
"""

from __future__ import annotations

from app.events.types import UpdateDetectedEvent
from app.utils.datetime import format_date, format_datetime
from app.utils.formatting import code_html


class TelegramFormatter:
    """Formats events into Telegram HTML strings."""

    @staticmethod
    def format_update_alert(
        event: UpdateDetectedEvent,
        timezone: str = "Europe/Moscow",
        language: str = "ru",
        patch_notes_html: str | None = None,
        patch_url: str | None = None,
        ai_analyzed: bool = False,
        depot_diff_html: str | None = None,
        patch_version: str | None = None,
        status_text: str | None = None,
        is_timeout: bool = False,
        is_waiting_datamine: bool = False,
    ) -> str:
        """
        Format an UpdateDetectedEvent for Telegram.

        Stage 1: instant alert with placeholder.
        Stage 2: edited alert with official patch notes while waiting for datamining.
        Stage 3: final enriched alert with player-friendly AI analysis + datamining (or clean timeout).
        """
        date_str = format_date(event.detected_at, timezone)
        if patch_version:
            title = f"🔄 <b>Обновление CS2 {code_html(patch_version)} · {date_str}</b>"
        else:
            title = f"🔄 <b>Обновление CS2 · {date_str}</b>"

        lines = [title]

        if patch_notes_html:
            lines.append("")
            if ai_analyzed:
                # Stage 3: Full AI + Datamining analysis
                lines.append(patch_notes_html)
            elif is_waiting_datamine:
                # Stage 2: Official patch notes displayed, still waiting for GitHub datamining
                lines.append("📋 <b>Официальный патчноут Valve</b>")
                lines.append("")
                lines.append(patch_notes_html)
                lines.append("")
                lines.append("🕵️ <i>Файлы обновления уже распаковываются датамайнерами, ищем скрытые изменения...</i>")
            else:
                # Official patch notes displayed (after datamining timeout or finished)
                lines.append("📋 <b>Официальный патчноут Valve</b>")
                lines.append("")
                lines.append(patch_notes_html)

            if patch_url:
                lines.append("")
                if "github.com" in patch_url:
                    lines.append(f'🔗 <a href="{patch_url}">Изменения файлов на GitHub</a>')
                else:
                    lines.append(f'🔗 <a href="{patch_url}">Официальный пост в Steam</a>')
        elif is_timeout:
            lines.append("")
            lines.append("ℹ️ <i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>")
        else:
            # Stage 1: Initial instant alert
            lines.append("")
            lines.append("⏳ <i>Вышло обновление! Ожидаем публикацию списка изменений от Valve...</i>")

        return "\n".join(lines)
