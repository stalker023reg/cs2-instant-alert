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
        banner_url: str | None = "https://cs2-instant-alert.fly.dev/static/banner.jpg",
    ) -> str:
        """
        Format an UpdateDetectedEvent for Telegram.

        Stage 1: instant alert with placeholder.
        Stage 2: edited alert with official patch notes while waiting for datamining.
        Stage 3: final enriched alert with player-friendly AI analysis + datamining (or clean timeout).
        """
        date_str = format_date(event.detected_at, timezone)
        banner_tag = f'<a href="{banner_url}">&#8205;</a>' if banner_url else ""
        is_en = (language or "").lower().startswith("en")

        if is_en:
            title = (
                f"{banner_tag}⚡ <b>CS2 Update • {code_html(patch_version)}</b>\n📅 <i>{date_str}</i>"
                if patch_version
                else f"{banner_tag}⚡ <b>CS2 Update</b>\n📅 <i>{date_str}</i>"
            )
        else:
            title = (
                f"{banner_tag}⚡ <b>Обновление CS2 • {code_html(patch_version)}</b>\n📅 <i>{date_str}</i>"
                if patch_version
                else f"{banner_tag}⚡ <b>Обновление CS2</b>\n📅 <i>{date_str}</i>"
            )

        lines = [title]

        if patch_notes_html:
            lines.append("")
            if ai_analyzed:
                # Stage 3: Full AI + Datamining analysis
                lines.append(patch_notes_html)
            elif is_waiting_datamine:
                # Stage 2: Official patch notes displayed, still waiting for GitHub datamining
                header = "📜 <b>Valve Official Patch Notes:</b>" if is_en else "📜 <b>Официальные изменения от Valve:</b>"
                footer = (
                    "🔎 <i>Dataminers are unpacking update files, searching for hidden changes...</i>"
                    if is_en
                    else "🔎 <i>Датамайнеры распаковывают файлы обновления, ищем скрытые изменения...</i>"
                )
                lines.append(header)
                lines.append("")
                lines.append(patch_notes_html)
                lines.append("")
                lines.append(footer)
            else:
                # Official patch notes displayed (after datamining timeout or finished)
                header = "📜 <b>Valve Official Patch Notes:</b>" if is_en else "📜 <b>Официальные изменения от Valve:</b>"
                lines.append(header)
                lines.append("")
                lines.append(patch_notes_html)

            if patch_url:
                lines.append("")
                steam_link = (
                    "https://store.steampowered.com/news/app/730"
                    if "github.com" in patch_url
                    else patch_url
                )
                link_text = "Official Steam Announcement" if is_en else "Официальный пост в Steam"
                lines.append(f'🌐 <a href="{steam_link}">{link_text}</a>')
        elif is_timeout:
            lines.append("")
            if is_en:
                lines.append("⚙️ <i>Technical binary update without gameplay, settings or UI changes.</i>")
            else:
                lines.append("⚙️ <i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>")
        else:
            # Stage 1: Initial instant alert
            lines.append("")
            if is_en:
                lines.append("⏳ <i>Patch is downloading on Steam. Awaiting official notes from Valve...</i>")
            else:
                lines.append("⏳ <i>Патч уже загружается в Steam. Ожидаем официальный список изменений от Valve...</i>")

        return "\n".join(lines)
