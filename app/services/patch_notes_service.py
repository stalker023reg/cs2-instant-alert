"""
CS2 Instant Alert — Patch Notes & Datamining Background Service.

Background service that polls for official patch notes (Steam News API)
and real datamining git diffs (GameTracking-CS2) after an update is detected,
runs AI analysis with Gemini Flash, and edits existing Telegram messages in-place.
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
from app.services.github_datamine_fetcher import GitHubDatamineFetcher
from app.services.steam_news_fetcher import SteamNewsFetcher
from app.services.translation_service import TranslationService
from app.utils.formatting import format_steam_patchnotes_html

if TYPE_CHECKING:
    from app.services.gemini_analysis_service import GeminiAnalysisService

logger = get_logger("system")


class PatchNotesService:
    """Polls for datamining diffs and patch notes, and updates delivered messages."""

    def __init__(
        self,
        session_factory,
        telegram_channel: TelegramChannel,
        settings: AppSettings,
        translation_service: TranslationService | None = None,
        gemini_service: GeminiAnalysisService | None = None,
        steam_news_fetcher: SteamNewsFetcher | None = None,
        github_fetcher: GitHubDatamineFetcher | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.telegram = telegram_channel
        self.settings = settings
        self.translation = translation_service
        self.gemini = gemini_service

        self.steam_news_fetcher = steam_news_fetcher or SteamNewsFetcher()
        github_token = (
            settings.github_token.get_secret_value()
            if settings.github_token
            else None
        )
        self.github_fetcher = github_fetcher or GitHubDatamineFetcher(github_token=github_token)

        self._tasks: set[asyncio.Task] = set()

    async def recover_pending_updates(self) -> None:
        """Find recent updates that haven't received datamining/patch notes and restart polling."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.update import Update

        now = datetime.now(UTC)
        ninety_mins_ago = now - timedelta(minutes=90)

        async with self.session_factory() as session:
            stmt = select(Update).where(Update.detected_at >= ninety_mins_ago)
            result = await session.execute(stmt)
            updates = result.scalars().all()

            for update in updates:
                history_stmt = select(NotificationHistory).where(
                    NotificationHistory.update_id == update.id,
                    NotificationHistory.last_edit_reason.in_([
                        "DATAMINE_ANALYZED",
                        "PATCH_NOTES_ADDED",
                        "DATAMINE_TIMEOUT",
                        "PATCH_NOTES_TIMEOUT",
                    ]),
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
                        depot_changes=update.depot_changes.get("changed") if update.depot_changes else None,
                    )
                    await self.start_polling_for_update(event)
                    await logger.ainfo("datamine_polling_recovered", update_id=str(update.id))

    async def start_polling_for_update(self, event: UpdateDetectedEvent) -> None:
        """
        Spawn a background task to poll for datamining diffs and patch notes.
        Polls every 45-60 seconds for up to 90 minutes.
        """
        task = asyncio.create_task(
            self._poll_loop(event),
            name=f"DataminePoll_{event.update_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _poll_loop(self, event: UpdateDetectedEvent) -> None:
        """
        Progressive 3-Stage Background Polling:
        - Stage 1: Already sent immediately on detection.
        - Stage 2: When Steam News API returns official patch notes (edit with official notes + wait for datamine).
        - Stage 3: When GameTracking-CS2 commit appears (final edit with full Gemini AI datamining).
        """
        start_time = datetime.now(UTC)
        max_duration = 90 * 60  # 90 minutes
        base_interval = 45  # 45 seconds initial interval

        has_posted_official_notes = False
        cached_news_item: Any | None = None

        await logger.ainfo(
            "datamine_polling_started",
            update_id=str(event.update_id),
            build_id=event.build_id,
        )

        try:
            while True:
                now = datetime.now(UTC)
                elapsed = (now - start_time).total_seconds()
                if elapsed > max_duration:
                    await logger.ainfo("datamine_polling_timeout", update_id=str(event.update_id))
                    await self._handle_timeout(event, cached_news_item)
                    break

                try:
                    # 1. Check Steam News API if we haven't found official patch notes yet
                    if not cached_news_item:
                        cached_news_item = await self.steam_news_fetcher.fetch_latest_patchnotes(event.detected_at)

                    # 2. Check GitHub GameTracking-CS2
                    datamine_commit = await self.github_fetcher.fetch_matching_commit(event.detected_at)

                    # If GitHub datamining is ready -> Final Stage 3!
                    if datamine_commit:
                        await logger.ainfo(
                            "datamine_commit_ready",
                            update_id=str(event.update_id),
                            sha=datamine_commit.commit_sha,
                            patch_version=datamine_commit.patch_version,
                        )
                        await self._process_and_edit_final(
                            event=event,
                            news_item=cached_news_item,
                            datamine_commit=datamine_commit,
                        )
                        return

                    # Stage 2: Official patch notes are ready, but datamining is still compiling
                    elif cached_news_item and not has_posted_official_notes:
                        await logger.ainfo(
                            "official_patchnotes_stage2_ready",
                            update_id=str(event.update_id),
                            url=cached_news_item.url,
                        )
                        await self._process_and_edit_stage2(
                            event=event,
                            news_item=cached_news_item,
                        )
                        has_posted_official_notes = True
                        # DO NOT return! Continue polling for GitHub datamining!

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await logger.aerror("datamine_polling_tick_error", error=str(e), exc_info=True)

                current_interval = base_interval if elapsed < 1800 else 60
                await asyncio.sleep(current_interval)

        except asyncio.CancelledError:
            pass

    async def _process_and_edit_stage2(
        self,
        event: UpdateDetectedEvent,
        news_item: Any,
    ) -> None:
        """Stage 2: Edit delivered Telegram messages with official patch notes while waiting for datamining."""
        raw_patch_notes = news_item.contents if news_item else ""
        patch_url = news_item.url if news_item else None

        formatted_html = format_steam_patchnotes_html(raw_patch_notes)
        if self.translation and self.translation.is_available:
            try:
                formatted_html = await self.translation.translate_to_russian(formatted_html)
            except Exception as e:
                await logger.awarning("official_patchnotes_translation_failed", error=str(e))

        # Update DB patch notes
        try:
            from app.repositories.update_repository import UpdateRepository

            async with self.session_factory() as session:
                update_repo = UpdateRepository(session)
                await update_repo.update_patch_notes(
                    event.update_id,
                    raw_patch_notes,
                    patch_url,
                )
                await session.commit()
        except Exception as db_err:
            await logger.awarning("stage2_db_update_failed", error=str(db_err))

        # Edit delivered messages with is_waiting_datamine=True
        await self._edit_messages(
            event=event,
            patch_notes_html=formatted_html,
            patch_url=patch_url,
            is_waiting_datamine=True,
            edit_reason="PATCH_NOTES_ADDED",
        )

    async def _process_and_edit_final(
        self,
        event: UpdateDetectedEvent,
        news_item: Any | None,
        datamine_commit: Any,
    ) -> None:
        """Stage 3: Run Gemini AI analysis on real diff + patch notes and edit delivered Telegram messages."""
        raw_patch_notes = news_item.contents if news_item else None
        patch_url = news_item.url if news_item else None

        git_diff = datamine_commit.filtered_diff if datamine_commit else None
        patch_version = datamine_commit.patch_version if datamine_commit else None

        manifest_changes = await self._get_manifest_changes(event.update_id)

        ai_analyzed = False
        formatted_html: str | None = None

        # ─── 1. Run Gemini Anti-Hallucination Analysis ───
        if self.gemini and self.gemini.is_available:
            try:
                analysis = await self.gemini.analyze_update(
                    raw_patch_notes=raw_patch_notes,
                    git_diff=git_diff,
                    patch_version=patch_version,
                    manifest_changes=manifest_changes,
                )
                formatted_html = analysis.summary_html
                ai_analyzed = True

                if analysis.error:
                    ai_analyzed = False

            except Exception as e:
                await logger.awarning("gemini_datamine_analysis_failed", error=str(e))
                ai_analyzed = False

        # ─── 2. Fallbacks if Gemini unavailable ───
        if not formatted_html:
            if raw_patch_notes:
                formatted_html = format_steam_patchnotes_html(raw_patch_notes)
                if self.translation and self.translation.is_available:
                    formatted_html = await self.translation.translate_to_russian(formatted_html)
            elif git_diff:
                formatted_html = "<i>Файлы обновления получены из GameTracking-CS2, но AI-анализ временно недоступен.</i>"
            else:
                formatted_html = "<i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>"

        # ─── 3. Update Database ───
        try:
            from app.repositories.update_repository import UpdateRepository

            async with self.session_factory() as session:
                update_repo = UpdateRepository(session)
                await update_repo.append_timeline_event(
                    update_id=event.update_id,
                    event_type="datamine_analysis_completed",
                    source="GitHub / Steam News",
                    metadata={
                        "patch_version": patch_version,
                        "commit_sha": datamine_commit.commit_sha if datamine_commit else None,
                        "news_gid": news_item.gid if news_item else None,
                        "ai_analyzed": ai_analyzed,
                    },
                )
                if patch_version:
                    update = await update_repo.get_by_id(event.update_id)
                    if update:
                        update.version = patch_version
                await update_repo.update_patch_notes(
                    event.update_id,
                    raw_patch_notes or "",
                    patch_url or (datamine_commit.commit_url if datamine_commit else None),
                )
                await session.commit()
        except Exception as db_err:
            await logger.awarning("datamine_db_update_failed", error=str(db_err))

        # ─── 4. Edit Delivered Messages with final report ───
        await self._edit_messages(
            event=event,
            patch_notes_html=formatted_html,
            patch_url=patch_url or (datamine_commit.commit_url if datamine_commit else None),
            patch_version=patch_version,
            ai_analyzed=ai_analyzed,
            is_timeout=False,
            is_waiting_datamine=False,
            edit_reason="DATAMINE_ANALYZED",
        )

    async def _handle_timeout(
        self,
        event: UpdateDetectedEvent,
        news_item: Any | None = None,
    ) -> None:
        """Handle 20-minute timeout when no datamining commit appeared."""
        if news_item and news_item.contents:
            raw_patch_notes = news_item.contents
            formatted_html = format_steam_patchnotes_html(raw_patch_notes)
            if self.translation and self.translation.is_available:
                try:
                    formatted_html = await self.translation.translate_to_russian(formatted_html)
                except Exception:
                    pass

            await self._edit_messages(
                event=event,
                patch_notes_html=formatted_html,
                patch_url=news_item.url,
                ai_analyzed=False,
                is_timeout=True,
                is_waiting_datamine=False,
                edit_reason="DATAMINE_TIMEOUT",
            )
        else:
            await self._edit_messages(
                event=event,
                patch_notes_html=None,
                patch_url=None,
                patch_version=None,
                ai_analyzed=False,
                is_timeout=True,
                is_waiting_datamine=False,
                edit_reason="PATCH_NOTES_TIMEOUT",
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
        patch_notes_html: str | None,
        patch_url: str | None = None,
        patch_version: str | None = None,
        is_timeout: bool = False,
        ai_analyzed: bool = False,
        depot_diff_html: str | None = None,
        is_waiting_datamine: bool = False,
        edit_reason: str = "DATAMINE_ANALYZED",
    ) -> None:
        """Find delivered Telegram messages for this update and edit them in-place."""
        from sqlalchemy import select

        async with self.session_factory() as session:
            repo = NotificationRepository(session)
            user_repo = UserRepository(session)

            stmt = select(NotificationHistory).where(
                NotificationHistory.update_id == event.update_id,
                NotificationHistory.channel_type == "telegram",
                NotificationHistory.provider_message_id.is_not(None),
            )
            result = await session.execute(stmt)
            histories = result.scalars().all()

            for history in histories:
                user = await user_repo.get_by_id(history.user_id)
                if user and history.provider_message_id:
                    await self.telegram.edit_update_alert(
                        user=user,
                        message_id=history.provider_message_id,
                        event=event,
                        patch_notes_html=patch_notes_html,
                        patch_url=patch_url,
                        ai_analyzed=ai_analyzed,
                        depot_diff_html=depot_diff_html,
                        patch_version=patch_version,
                        is_timeout=is_timeout,
                        is_waiting_datamine=is_waiting_datamine,
                    )

                    await repo.update_history(
                        history,
                        last_edit_reason=edit_reason,
                        edited_at=datetime.now(UTC),
                        current_message_version=history.current_message_version + 1,
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
                            "patch_version": patch_version,
                            "is_timeout": is_timeout,
                            "is_waiting_datamine": is_waiting_datamine,
                            "edit_reason": edit_reason,
                        },
                    )

            await session.commit()

    async def stop(self) -> None:
        """Cancel all running polling tasks."""
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
