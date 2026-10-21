"""
CS2 Instant Alert — Patch Notes Service.

Background service that polls for official patch notes after an update
is detected, and edits existing Telegram messages to include them.

Supports two analysis modes:
  1. AI Analysis (Gemini 2.5 Flash) — structured summary with categories
  2. DeepL Translation — literal translation fallback
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.config import AppSettings
from app.core.constants import CS2_APP_ID
from app.core.logging import get_logger
from app.events.types import UpdateDetectedEvent
from app.models.notification_history import NotificationHistory
from app.notifications.channels.telegram import TelegramChannel
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.translation_service import TranslationService
from app.utils.formatting import format_steam_patchnotes_html

if TYPE_CHECKING:
    from app.services.gemini_analysis_service import GeminiAnalysisService

logger = get_logger("system")


class PatchNotesService:
    """Polls for patch notes and updates delivered messages."""

    def __init__(
        self,
        session_factory,
        telegram_channel: TelegramChannel,
        settings: AppSettings,
        translation_service: TranslationService | None = None,
        gemini_service: GeminiAnalysisService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.telegram = telegram_channel
        self.settings = settings
        self.translation = translation_service
        self.gemini = gemini_service
        self._tasks: set[asyncio.Task] = set()

    async def recover_pending_updates(self) -> None:
        """Finds recent updates that haven't received patch notes and restarts polling."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.update import Update

        now = datetime.now(UTC)
        thirty_mins_ago = now - timedelta(minutes=30)

        async with self.session_factory() as session:
            stmt = select(Update).where(Update.detected_at >= thirty_mins_ago)
            result = await session.execute(stmt)
            updates = result.scalars().all()

            for update in updates:
                history_stmt = select(NotificationHistory).where(
                    NotificationHistory.update_id == update.id,
                    NotificationHistory.last_edit_reason.in_(["PATCH_NOTES_ADDED", "PATCH_NOTES_TIMEOUT"])
                )
                history_result = await session.execute(history_stmt)
                if not history_result.scalars().first():
                    from app.steam.types import AppUpdateData
                    event = UpdateDetectedEvent(
                        update_id=update.id,
                        game_id=update.game_id,
                        build_id=update.build_id,
                        previous_build_id=update.previous_build_id,
                        is_critical=False,
                        detected_at=update.detected_at,
                        raw_data=(
                            AppUpdateData(**update.raw_data)
                            if update.raw_data
                            else AppUpdateData(
                                app_id=CS2_APP_ID,
                                source="pics",
                                checked_at=update.detected_at,
                            )
                        ),
                    )
                    await self.start_polling_for_update(event)
                    await logger.ainfo("patch_notes_polling_recovered", update_id=str(update.id))

    async def start_polling_for_update(self, event: UpdateDetectedEvent) -> None:
        """
        Spawn a background task to poll for patch notes for this specific update.
        Will poll for up to 30 minutes.
        """
        task = asyncio.create_task(
            self._poll_loop(event),
            name=f"PatchNotesPoll_{event.update_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _poll_loop(self, event: UpdateDetectedEvent) -> None:
        """Polls Steam News API for patch notes."""
        start_time = datetime.now(UTC)
        max_duration = 15 * 60  # 15 minutes
        poll_interval = 60  # 1 minute

        await logger.ainfo("patch_notes_polling_started", update_id=str(event.update_id))

        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                while True:
                    try:
                        now = datetime.now(UTC)
                        if (now - start_time).total_seconds() > max_duration:
                            await logger.ainfo("patch_notes_polling_timeout", update_id=str(event.update_id))
                            await self._process_silent_update_and_edit(event)
                            break

                        # Steam News expects the numeric app id, not our database UUID.
                        url = f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={CS2_APP_ID}&count=3"
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            data = resp.json()
                            newsitems = data.get("appnews", {}).get("newsitems", [])

                            for item in newsitems:
                                # Check if it's a patch notes post
                                title = item.get("title", "").lower()
                                if "release notes" in title or "update" in title:
                                    post_date = datetime.fromtimestamp(item.get("date", 0), tz=UTC)
                                    time_diff = abs((post_date - event.detected_at).total_seconds())
                                    if time_diff < 7200:
                                        await logger.ainfo("PatchNotesFound", update_id=str(event.update_id))

                                        from app.repositories.update_repository import (
                                            UpdateRepository,
                                        )
                                        async with self.session_factory() as temp_session:
                                            update_repo = UpdateRepository(temp_session)
                                            await update_repo.append_timeline_event(
                                                update_id=event.update_id,
                                                event_type="patch_notes_found",
                                                source="Steam Web API",
                                                metadata={"gid": item.get('gid', '')}
                                            )
                                            patch_url = (
                                                f"https://steamcommunity.com/games/{CS2_APP_ID}"
                                                f"/announcements/detail/{item.get('gid', '')}"
                                            )
                                            await update_repo.update_patch_notes(
                                                event.update_id,
                                                item.get("contents", ""),
                                                patch_url,
                                            )
                                            await temp_session.commit()

                                        # ─── Process patch notes ───
                                        raw_contents = item.get("contents", "")
                                        await self._process_and_edit(
                                            event, raw_contents, patch_url,
                                        )
                                        return
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        await logger.aerror("patch_notes_polling_error", error=str(e), exc_info=True)

                    await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            pass

    async def _process_and_edit(
        self,
        event: UpdateDetectedEvent,
        raw_contents: str,
        patch_url: str,
    ) -> None:
        """
        Process raw patch notes through AI or translation, then edit messages.

        Priority:
          1. Gemini AI analysis (structured summary + depot diff)
          2. DeepL translation (literal translation, fallback)
          3. BB-code formatting only (no translation)
        """
        ai_analyzed = False
        depot_diff_html: str | None = None
        formatted_html: str | None = None

        # ─── Try AI analysis first ───
        if self.gemini and self.gemini.is_available:
            try:
                # Fetch manifest changes for depot diff context
                manifest_changes = await self._get_manifest_changes(event.update_id)

                analysis = await self.gemini.analyze_update(
                    raw_patch_notes=raw_contents,
                    manifest_changes=manifest_changes,
                )

                formatted_html = analysis.summary_html
                depot_diff_html = analysis.depot_diff_html
                ai_analyzed = True

                await logger.ainfo(
                    "patch_notes_ai_analyzed",
                    update_id=str(event.update_id),
                    has_depot_diff=bool(depot_diff_html),
                    error=analysis.error,
                )

                # If AI analysis had an error, it already fell back internally
                if analysis.error:
                    ai_analyzed = False

            except Exception as e:
                await logger.awarning(
                    "gemini_analysis_skipped",
                    error=str(e),
                    update_id=str(event.update_id),
                )
                formatted_html = None
                ai_analyzed = False

        # ─── Fallback: DeepL translation or basic formatting ───
        if not ai_analyzed or formatted_html is None:
            formatted_html = format_steam_patchnotes_html(raw_contents)

            # Translate to Russian via DeepL
            if self.translation and self.translation.is_available:
                formatted_html = await self.translation.translate_to_russian(formatted_html)

        await self._edit_messages(
            event,
            formatted_html,
            patch_url,
            ai_analyzed=ai_analyzed,
            depot_diff_html=depot_diff_html,
        )

    async def _process_silent_update_and_edit(
        self,
        event: UpdateDetectedEvent,
    ) -> None:
        """
        Handle a silent update when no patch notes are published by Valve.

        Runs Gemini AI analysis purely on the changed depots, then edits messages.
        """
        ai_analyzed = False
        depot_diff_html: str | None = None
        formatted_html: str | None = None

        manifest_changes = await self._get_manifest_changes(event.update_id)

        if self.gemini and self.gemini.is_available:
            try:
                analysis = await self.gemini.analyze_update(
                    raw_patch_notes=None,
                    manifest_changes=manifest_changes,
                )
                formatted_html = analysis.summary_html
                depot_diff_html = analysis.depot_diff_html
                ai_analyzed = True

                await logger.ainfo(
                    "silent_update_ai_analyzed",
                    update_id=str(event.update_id),
                    has_depot_diff=bool(depot_diff_html),
                    error=analysis.error,
                )

                if analysis.error:
                    ai_analyzed = False
            except Exception as e:
                await logger.awarning(
                    "silent_update_gemini_skipped",
                    error=str(e),
                    update_id=str(event.update_id),
                )
                ai_analyzed = False

        if not formatted_html or not ai_analyzed:
            formatted_html = "<i>Официальные patch notes не опубликованы (бесшумный патч / технический хотфикс).</i>"
            if self.gemini and manifest_changes:
                depot_diff_html = self.gemini._format_depot_diff_html(manifest_changes)

        await self._edit_messages(
            event,
            formatted_html,
            patch_url=None,
            is_timeout=False,
            ai_analyzed=ai_analyzed,
            depot_diff_html=depot_diff_html,
        )

    async def _get_manifest_changes(self, update_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch manifest changes from the Update record for depot diff context."""
        try:
            async with self.session_factory() as session:
                from app.repositories.update_repository import UpdateRepository
                repo = UpdateRepository(session)
                update = await repo.get_by_id(update_id)
                if update:
                    if update.depot_changes and isinstance(update.depot_changes, dict):
                        changed = update.depot_changes.get("changed")
                        if changed:
                            return changed
                    if update.manifest_changes:
                        return update.manifest_changes
        except Exception as e:
            await logger.awarning("manifest_changes_fetch_failed", error=str(e))
        return None

    async def _edit_messages(
        self,
        event: UpdateDetectedEvent,
        patch_notes_html: str,
        patch_url: str | None = None,
        is_timeout: bool = False,
        ai_analyzed: bool = False,
        depot_diff_html: str | None = None,
    ) -> None:
        """Find delivered Telegram messages for this update and edit them."""
        from sqlalchemy import select
        async with self.session_factory() as session:
            repo = NotificationRepository(session)
            user_repo = UserRepository(session)

            stmt = select(NotificationHistory).where(
                NotificationHistory.update_id == event.update_id,
                NotificationHistory.channel_type == "telegram",
                NotificationHistory.provider_message_id.is_not(None)
            )
            result = await session.execute(stmt)
            histories = result.scalars().all()

            for history in histories:
                user = await user_repo.get_by_id(history.user_id)
                if user and history.provider_message_id:
                    if is_timeout:
                        await repo.update_history(history, last_edit_reason="PATCH_NOTES_TIMEOUT")
                    else:
                        await self.telegram.edit_update_alert(
                            user=user,
                            message_id=history.provider_message_id,
                            event=event,
                            patch_notes_html=patch_notes_html,
                            patch_url=patch_url,
                            ai_analyzed=ai_analyzed,
                            depot_diff_html=depot_diff_html,
                        )
                        edit_reason = "SILENT_UPDATE_ANALYZED" if patch_url is None else "PATCH_NOTES_ADDED"
                        await repo.update_history(
                            history,
                            last_edit_reason=edit_reason,
                            edited_at=datetime.now(UTC),
                            current_message_version=history.current_message_version + 1
                        )

                        from app.repositories.update_repository import UpdateRepository
                        update_repo = UpdateRepository(session)
                        await update_repo.append_timeline_event(
                            update_id=event.update_id,
                            event_type="message_edited",
                            source="Telegram Channel",
                            metadata={
                                "user_id": str(user.id),
                                "message_id": history.provider_message_id,
                                "ai_analyzed": ai_analyzed,
                            }
                        )
            await session.commit()

    async def stop(self) -> None:
        """Cancel all running polling tasks."""
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
