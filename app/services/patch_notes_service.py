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
        twenty_mins_ago = now - timedelta(minutes=20)

        async with self.session_factory() as session:
            stmt = select(Update).where(Update.detected_at >= twenty_mins_ago)
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
        Polls every 45 seconds for up to 20 minutes.
        """
        task = asyncio.create_task(
            self._poll_loop(event),
            name=f"DataminePoll_{event.update_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _poll_loop(self, event: UpdateDetectedEvent) -> None:
        """
        Stage 2 Background Polling:
        Every 45 seconds checks Steam News API and GameTracking-CS2.
        """
        start_time = datetime.now(UTC)
        max_duration = 20 * 60  # 20 minutes
        poll_interval = 45  # 45 seconds

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
                    await self._handle_timeout(event)
                    break

                try:
                    # 1. Check Steam News API
                    news_item = await self.steam_news_fetcher.fetch_latest_patchnotes(event.detected_at)

                    # 2. Check GitHub GameTracking-CS2
                    datamine_commit = await self.github_fetcher.fetch_matching_commit(event.detected_at)

                    # If we found datamining commit OR official patch notes, process and edit!
                    if news_item or datamine_commit:
                        await logger.ainfo(
                            "datamine_source_ready",
                            update_id=str(event.update_id),
                            has_news=bool(news_item),
                            has_commit=bool(datamine_commit),
                            patch_version=datamine_commit.patch_version if datamine_commit else None,
                        )

                        await self._process_and_edit(
                            event=event,
                            news_item=news_item,
                            datamine_commit=datamine_commit,
                        )
                        return

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await logger.aerror("datamine_polling_tick_error", error=str(e), exc_info=True)

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            pass

    async def _process_and_edit(
        self,
        event: UpdateDetectedEvent,
        news_item: Any | None,
        datamine_commit: Any | None,
    ) -> None:
        """Run LLM analysis on real diff + patch notes and edit delivered Telegram messages."""
        raw_patch_notes = news_item.contents if news_item else None
        patch_url = news_item.url if news_item else None

        git_diff = datamine_commit.filtered_diff if datamine_commit else None
        patch_version = datamine_commit.patch_version if datamine_commit else None

        manifest_changes = await self._get_manifest_changes(event.update_id)

        ai_analyzed = False
        formatted_html: str | None = None
        depot_diff_html: str | None = None

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
                depot_diff_html = analysis.depot_diff_html
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
                await update_repo.update_patch_notes(
                    event.update_id,
                    raw_patch_notes or "",
                    patch_url or (datamine_commit.commit_url if datamine_commit else None),
                )
                await session.commit()
        except Exception as db_err:
            await logger.awarning("datamine_db_update_failed", error=str(db_err))

        # ─── 4. Edit Delivered Messages ───
        await self._edit_messages(
            event=event,
            patch_notes_html=formatted_html,
            patch_url=patch_url,
            patch_version=patch_version,
            ai_analyzed=ai_analyzed,
            depot_diff_html=depot_diff_html,
            is_timeout=False,
        )

    async def _handle_timeout(self, event: UpdateDetectedEvent) -> None:
        """Handle 20-minute timeout when no commit or patch notes appeared."""
        await self._edit_messages(
            event=event,
            patch_notes_html=None,
            patch_url=None,
            patch_version=None,
            ai_analyzed=False,
            depot_diff_html=None,
            is_timeout=True,
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
                    )

                    edit_reason = "DATAMINE_TIMEOUT" if is_timeout else "DATAMINE_ANALYZED"
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
                        },
                    )

            await session.commit()

    async def stop(self) -> None:
        """Cancel all running polling tasks."""
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
