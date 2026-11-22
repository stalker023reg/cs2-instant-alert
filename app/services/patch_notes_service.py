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
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.services.gemini_analysis_service import GeminiAnalysisService

logger = get_logger("system")


class PatchNotesService:
    """Polls for datamining diffs and patch notes, and updates delivered messages."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | Any,
        telegram_channel: TelegramChannel,
        settings: AppSettings,
        translation_service: TranslationService | None = None,
        gemini_service: GeminiAnalysisService | None = None,
        steam_news_fetcher: SteamNewsFetcher | None = None,
        github_fetcher: GitHubDatamineFetcher | None = None,
        x_publisher: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.telegram = telegram_channel
        self.settings = settings
        self.translation = translation_service
        self.gemini = gemini_service
        self.x_publisher = x_publisher

        self.steam_news_fetcher = steam_news_fetcher or SteamNewsFetcher()
        github_token = (
            settings.github_token.get_secret_value()
            if settings.github_token
            else None
        )
        self.github_fetcher = github_fetcher or GitHubDatamineFetcher(github_token=github_token)

        self._tasks: set[asyncio.Task[Any]] = set()
        self._x_publishing_updates: set[uuid.UUID] = set()

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
        Progressive 3-Stage Background Polling with Smart Patchnotes Waiting:
        - Stage 1: Already sent immediately on detection.
        - Stage 2: When Steam News API returns official patch notes while waiting for datamine.
        - Stage 3: Enriched final report combining official Valve patch notes + deep git datamining.
                   Waits up to 25 minutes for Valve's official patch notes so they are merged
                   together into one definitive, professional update digest.
        """
        start_time = datetime.now(UTC)
        max_duration = 45 * 60  # 45 minutes overall timeout
        base_interval = 30  # 30 seconds interval
        max_news_wait_seconds = 25 * 60  # 25 minutes wait window for Valve's release notes

        has_posted_official_notes = False
        cached_news_item: Any | None = None
        cached_datamine_commit: Any | None = None
        has_logged_wait_for_news = False

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
                    if cached_datamine_commit:
                        await self._process_and_edit_final(
                            event=event,
                            news_item=cached_news_item,
                            datamine_commit=cached_datamine_commit,
                        )
                    else:
                        await self._handle_timeout(event, cached_news_item)
                    break

                try:
                    # 1. Check Steam News API if we haven't found official patch notes yet
                    if not cached_news_item:
                        cached_news_item = await self.steam_news_fetcher.fetch_latest_patchnotes(event.detected_at)

                    # 2. Check GitHub GameTracking-CS2 if we haven't found matching commit yet
                    if not cached_datamine_commit:
                        cached_datamine_commit = await self.github_fetcher.fetch_matching_commit(event.detected_at)
                        if cached_datamine_commit:
                            await logger.ainfo(
                                "datamine_commit_ready",
                                update_id=str(event.update_id),
                                sha=cached_datamine_commit.commit_sha,
                                patch_version=cached_datamine_commit.patch_version,
                            )

                    # 3. Decision Logic:
                    # Case A: BOTH official notes and datamining are ready -> Complete definitive report!
                    if cached_datamine_commit and cached_news_item:
                        await logger.ainfo(
                            "datamine_and_official_notes_both_ready",
                            update_id=str(event.update_id),
                            news_gid=cached_news_item.gid,
                            commit_sha=cached_datamine_commit.commit_sha,
                        )
                        await self._process_and_edit_final(
                            event=event,
                            news_item=cached_news_item,
                            datamine_commit=cached_datamine_commit,
                        )
                        return

                    # Case B: Datamining is ready, but Valve's official patch notes are not out yet
                    elif cached_datamine_commit and not cached_news_item:
                        if elapsed < max_news_wait_seconds:
                            if not has_logged_wait_for_news:
                                await logger.ainfo(
                                    "datamine_ready_waiting_for_official_patchnotes",
                                    update_id=str(event.update_id),
                                    wait_timeout_seconds=int(max_news_wait_seconds - elapsed),
                                )
                                has_logged_wait_for_news = True
                            # Continue polling Steam News every interval
                        else:
                            # 25-minute window for Valve patch notes expired -> silent update or hotfix without notes
                            await logger.ainfo(
                                "official_patchnotes_wait_expired_finalizing_with_datamine_only",
                                update_id=str(event.update_id),
                            )
                            await self._process_and_edit_final(
                                event=event,
                                news_item=None,
                                datamine_commit=cached_datamine_commit,
                            )
                            return

                    # Case C: Official patch notes arrived FIRST, datamining still compiling
                    elif cached_news_item and not cached_datamine_commit:
                        if not has_posted_official_notes:
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
                        # Continue polling for GitHub datamining!

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await logger.aerror("datamine_polling_tick_error", error=str(e), exc_info=True)

                current_interval = base_interval if elapsed < 1200 else 45
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

        formatted_html_en = format_steam_patchnotes_html(raw_patch_notes)
        formatted_html_ru = formatted_html_en
        if self.translation and self.translation.is_available:
            try:
                formatted_html_ru = await self.translation.translate_to_russian(formatted_html_en)
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
            patch_notes_html=formatted_html_ru,
            patch_notes_html_en=formatted_html_en,
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
        steam_patch_url = patch_url or "https://store.steampowered.com/news/app/730"

        git_diff = datamine_commit.filtered_diff if datamine_commit else None
        patch_version = datamine_commit.patch_version if datamine_commit else None

        manifest_changes = await self._get_manifest_changes(event.update_id)

        ai_analyzed = False
        formatted_html_ru: str | None = None
        formatted_html_en: str | None = None

        # ─── 1. Run Gemini Anti-Hallucination Analysis ───
        if self.gemini and self.gemini.is_available:
            try:
                analysis_ru = await self.gemini.analyze_update(
                    raw_patch_notes=raw_patch_notes,
                    git_diff=git_diff,
                    patch_version=patch_version,
                    manifest_changes=manifest_changes,
                    language="ru",
                )
                formatted_html_ru = analysis_ru.summary_html
                if not analysis_ru.error:
                    ai_analyzed = True

                # Generate English version for English channels/groups (only if needed)
                need_english = getattr(self.settings, "x_enabled", False)
                if not need_english:
                    try:
                        from app.repositories.user_repository import UserRepository

                        async with self.session_factory() as session:
                            user_repo = UserRepository(session)
                            active_users = await user_repo.get_active_users()
                            need_english = any(
                                (getattr(u, "language", "ru") or "").lower().startswith("en")
                                for u in active_users
                            )
                    except Exception as chk_err:
                        await logger.awarning("check_english_recipients_failed", error=str(chk_err))
                        need_english = False

                if need_english:
                    try:
                        analysis_en = await self.gemini.analyze_update(
                            raw_patch_notes=raw_patch_notes,
                            git_diff=git_diff,
                            patch_version=patch_version,
                            manifest_changes=manifest_changes,
                            language="en",
                        )
                        formatted_html_en = analysis_en.summary_html
                    except Exception as en_err:
                        await logger.awarning("gemini_english_analysis_failed", error=str(en_err))
                        formatted_html_en = None
                else:
                    await logger.ainfo(
                        "skip_english_gemini_analysis",
                        reason="no_english_recipients_and_x_disabled",
                    )

            except Exception as e:
                await logger.awarning("gemini_datamine_analysis_failed", error=str(e))
                ai_analyzed = False

        # ─── 2. Fallbacks if Gemini unavailable ───
        if not formatted_html_ru:
            if raw_patch_notes:
                formatted_raw = format_steam_patchnotes_html(raw_patch_notes)
                formatted_html_en = formatted_raw
                if self.translation and self.translation.is_available:
                    try:
                        formatted_html_ru = await self.translation.translate_to_russian(formatted_raw)
                    except Exception:
                        formatted_html_ru = formatted_raw
                else:
                    formatted_html_ru = formatted_raw
            elif git_diff:
                formatted_html_ru = "<i>Файлы обновления получены из GameTracking-CS2, но AI-анализ временно недоступен.</i>"
                formatted_html_en = "<i>GameTracking-CS2 files updated, but AI analysis is temporarily unavailable.</i>"
            else:
                formatted_html_ru = "<i>Техническое обновление исполняемых файлов без изменений в геймплее, настройках и интерфейсе.</i>"
                formatted_html_en = "<i>Technical binary update without gameplay, settings or UI changes.</i>"

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
                steam_patch_url = patch_url or "https://store.steampowered.com/news/app/730"
                await update_repo.update_patch_notes(
                    event.update_id,
                    raw_patch_notes or "",
                    steam_patch_url,
                )
                await session.commit()
        except Exception as db_err:
            await logger.awarning("datamine_db_update_failed", error=str(db_err))

        # ─── 4. Edit Delivered Messages with final report ───
        await self._edit_messages(
            event=event,
            patch_notes_html=formatted_html_ru,
            patch_notes_html_en=formatted_html_en,
            patch_url=steam_patch_url,
            patch_version=patch_version,
            ai_analyzed=ai_analyzed,
            is_timeout=False,
            is_waiting_datamine=False,
            edit_reason="DATAMINE_ANALYZED",
        )

        # ─── 5. Publish to X (Twitter) on Stage 3 ───
        await self._publish_to_x_if_needed(
            event=event,
            en_text=formatted_html_en or formatted_html_ru or "",
            patch_version=patch_version,
        )

    async def _publish_to_x_if_needed(
        self,
        event: UpdateDetectedEvent,
        en_text: str | None,
        patch_version: str | None = None,
    ) -> None:
        """Publish update thread to X with state tracking and deduplication."""
        if not self.x_publisher or not getattr(self.settings, "x_enabled", False):
            return

        if not en_text or not en_text.strip():
            return

        # 1. In-memory concurrency guard
        if event.update_id in self._x_publishing_updates:
            await logger.ainfo("x_publish_already_in_progress", update_id=str(event.update_id))
            return

        self._x_publishing_updates.add(event.update_id)
        try:
            # 2. Database deduplication & publication status check
            from app.repositories.update_repository import UpdateRepository

            async with self.session_factory() as session:
                update_repo = UpdateRepository(session)
                x_info = await update_repo.get_x_thread_info(event.update_id)
                if x_info and x_info.get("status") == "published":
                    await logger.ainfo("x_publish_already_published", update_id=str(event.update_id))
                    return

            from pathlib import Path
            from app.notifications.x_formatter import XThreadFormatter

            banner_path = Path(__file__).resolve().parent.parent / "static" / "banner.jpg"

            # Format as single comprehensive post for X Premium
            single_post = XThreadFormatter.format_single_post(
                event=event,
                analysis_en=en_text,
                patch_version=patch_version,
            )
            thread = [single_post]

            new_tweet_ids = await self.x_publisher.publish_thread(
                thread,
                banner_path=banner_path,
            )
            all_posted_ids = new_tweet_ids

            if all_posted_ids:
                is_full = len(all_posted_ids) >= len(thread)
                event_type = "x_thread_published" if is_full else "x_thread_partial"

                async with self.session_factory() as session:
                    update_repo = UpdateRepository(session)
                    await update_repo.append_timeline_event(
                        update_id=event.update_id,
                        event_type=event_type,
                        source="X / Twitter (@cs2_alert)",
                        metadata={
                            "tweet_ids": all_posted_ids,
                            "root_tweet_id": all_posted_ids[0],
                            "last_tweet_id": all_posted_ids[-1],
                            "tweets_count": len(all_posted_ids),
                            "total_tweets": len(thread),
                            "is_complete": is_full,
                        },
                    )
                    await session.commit()

                if is_full:
                    await logger.ainfo(
                        "x_thread_published_successfully",
                        update_id=str(event.update_id),
                        root_tweet_id=all_posted_ids[0],
                        count=len(all_posted_ids),
                    )
                else:
                    await logger.awarning(
                        "x_thread_partially_published",
                        update_id=str(event.update_id),
                        posted_count=len(all_posted_ids),
                        total_expected=len(thread),
                    )
        except Exception as x_err:
            await logger.awarning("x_publish_failed", update_id=str(event.update_id), error=str(x_err))
        finally:
            self._x_publishing_updates.discard(event.update_id)

    async def _handle_timeout(
        self,
        event: UpdateDetectedEvent,
        news_item: Any | None = None,
    ) -> None:
        """Handle 20-minute timeout when no datamining commit appeared."""
        if news_item and news_item.contents:
            raw_patch_notes = news_item.contents
            formatted_html_en = format_steam_patchnotes_html(raw_patch_notes)
            formatted_html_ru = formatted_html_en
            if self.translation and self.translation.is_available:
                try:
                    formatted_html_ru = await self.translation.translate_to_russian(formatted_html_en)
                except Exception:
                    pass

            await self._edit_messages(
                event=event,
                patch_notes_html=formatted_html_ru,
                patch_notes_html_en=formatted_html_en,
                patch_url=news_item.url,
                ai_analyzed=False,
                is_timeout=True,
                is_waiting_datamine=False,
                edit_reason="DATAMINE_TIMEOUT",
            )

            # Publish official patch notes to X even if GitHub datamine timed out
            await self._publish_to_x_if_needed(
                event=event,
                en_text=formatted_html_en or formatted_html_ru or "",
                patch_version=None,
            )
        else:
            await self._edit_messages(
                event=event,
                patch_notes_html=None,
                patch_notes_html_en=None,
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
                        if isinstance(changed, dict):
                            return changed
                    if isinstance(update.manifest_changes, dict):
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
        patch_notes_html_en: str | None = None,
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
                    user_is_en = (user.language or "").lower().startswith("en")
                    user_patch_notes = (
                        patch_notes_html_en if (user_is_en and patch_notes_html_en) else patch_notes_html
                    )
                    await self.telegram.edit_update_alert(
                        user=user,
                        message_id=history.provider_message_id,
                        event=event,
                        patch_notes_html=user_patch_notes,
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
