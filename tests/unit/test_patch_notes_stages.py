from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from app.events.types import UpdateDetectedEvent
from app.services.patch_notes_service import PatchNotesService
from app.steam.types import AppUpdateData, SteamSource


class TestPatchNotesStages(unittest.IsolatedAsyncioTestCase):
    async def test_patch_notes_service_progressive_stages(self):
        """Verify Stage 2 (official notes) and Stage 3 (datamining commit) flow."""
        mock_session = AsyncMock()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__.return_value = mock_session
        telegram_channel = MagicMock()
        telegram_channel.edit_update_alert = AsyncMock()

        settings = MagicMock()
        settings.github_token = None

        steam_news_fetcher = MagicMock()
        github_fetcher = MagicMock()
        gemini_service = MagicMock()
        gemini_service.is_available = True
        gemini_service.analyze_update = AsyncMock()
        gemini_service.analyze_update.return_value = MagicMock(
            summary_html="🧰 <b>Дополненный патчноут</b>\n• Test",
            error=None,
        )

        service = PatchNotesService(
            session_factory=session_factory,
            telegram_channel=telegram_channel,
            settings=settings,
            gemini_service=gemini_service,
            steam_news_fetcher=steam_news_fetcher,
            github_fetcher=github_fetcher,
        )

        event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="26281801",
            previous_build_id="26144732",
            is_critical=False,
            detected_at=datetime.now(UTC),
            raw_data=AppUpdateData(
                app_id=730,
                source=SteamSource.PICS,
                checked_at=datetime.now(UTC),
            ),
        )

        # 1. First tick: Steam news exists, GitHub commit does NOT exist yet
        mock_news = MagicMock()
        mock_news.contents = "[p]Added Silent reload[/p]"
        mock_news.url = "https://steam/123"
        mock_news.gid = "123"

        steam_news_fetcher.fetch_latest_patchnotes = AsyncMock(return_value=mock_news)
        github_fetcher.fetch_matching_commit = AsyncMock(return_value=None)

        with patch("app.repositories.update_repository.UpdateRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.update_patch_notes = AsyncMock()
            mock_repo.append_timeline_event = AsyncMock()
            mock_repo.get_by_id = AsyncMock(return_value=MagicMock())
            mock_repo_cls.return_value = mock_repo

            with patch.object(service, "_edit_messages", new_callable=AsyncMock) as mock_edit:
                # Run stage 2
                await service._process_and_edit_stage2(event, mock_news)
                mock_edit.assert_called_once()
                _, kwargs = mock_edit.call_args
                self.assertTrue(kwargs["is_waiting_datamine"])
                self.assertEqual(kwargs["edit_reason"], "PATCH_NOTES_ADDED")

            # 2. Second tick: GitHub commit appears!
            mock_commit = MagicMock()
            mock_commit.commit_sha = "b73cfdeb35"
            mock_commit.commit_url = "https://github.com/commit/123"
            mock_commit.patch_version = "1.41.9.3"
            mock_commit.filtered_diff = "diff..."

            with patch.object(service, "_edit_messages", new_callable=AsyncMock) as mock_edit:
                with patch.object(service, "_get_manifest_changes", new_callable=AsyncMock, return_value=None):
                    await service._process_and_edit_final(event, mock_news, mock_commit)
                    mock_edit.assert_called_once()
                    _, kwargs = mock_edit.call_args
                    self.assertFalse(kwargs["is_waiting_datamine"])
                    self.assertTrue(kwargs["ai_analyzed"])
                    self.assertEqual(kwargs["patch_version"], "1.41.9.3")
                    self.assertEqual(kwargs["edit_reason"], "DATAMINE_ANALYZED")


if __name__ == "__main__":
    unittest.main()
