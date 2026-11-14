from __future__ import annotations

import unittest
import uuid
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from app.core.config import AppSettings
from app.events.types import UpdateDetectedEvent
from app.notifications.x_formatter import XThreadFormatter
from app.services.x_publisher_service import XPublisherService
from app.steam.types import AppUpdateData, SteamSource


class TestXIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.event = UpdateDetectedEvent(
            update_id=uuid.uuid4(),
            game_id=uuid.uuid4(),
            build_id="26598758",
            previous_build_id="26445667",
            detected_at=datetime(2026, 11, 12, 23, 0, 0, tzinfo=UTC),
            is_critical=False,
            raw_data=AppUpdateData(app_id=730, source=SteamSource.PICS, checked_at=datetime.now(UTC)),
        )

    def test_thread_formatter_splits_properly_and_respects_limits(self):
        analysis = """🎯 <b>Key Highlights:</b>
• <b>Retakes Bot AI:</b> Overhauled bot pathfinding and tactics. One CT now defuses while others push.
• <b>DX11 Fix:</b> Resolved rendering freezes.

🔎 <b>Game File Discoveries:</b>
• <b>Frost:</b> Added dynamic frost mechanic on players and chickens.
• <b>POM:</b> Added parallax occlusion mapping in video options."""

        thread = XThreadFormatter.format_thread(
            event=self.event,
            analysis_en=analysis,
            patch_version="1.41.9.7",
            patch_url="https://github.com/diff",
            telegram_channel_url="https://t.me/cs2_alarm",
        )

        self.assertGreaterEqual(len(thread), 3)
        self.assertIn("🚨 CS2 Update • 1.41.9.7 is LIVE!", thread[0])
        self.assertIn("https://t.me/cs2_alarm", thread[-1])
        self.assertNotIn("github.com", thread[-1])  # Excluded intentionally
        self.assertIn("#CS2", thread[-1])

        for idx, tweet in enumerate(thread, start=1):
            self.assertTrue(tweet.startswith(f"[{idx}/{len(thread)}]"))
            self.assertLessEqual(len(tweet), 280)

    def test_thread_formatter_with_curated_tweets(self):
        curated = [
            "🎯 Major map rework on Inferno and Vertigo with new bombsite layouts.",
            "🔎 Datamined 3 new knife models and weapon charm slots.",
        ]
        thread = XThreadFormatter.format_thread(
            event=self.event,
            analysis_en="Full text",
            patch_version="1.41.9.8",
            telegram_channel_url="https://t.me/cs2_alarm",
            curated_tweets=curated,
        )

        self.assertEqual(len(thread), 4)  # 1 root + 2 curated + 1 final
        self.assertIn("Inferno and Vertigo", thread[1])
        self.assertIn("knife models", thread[2])
        self.assertIn("https://t.me/cs2_alarm", thread[3])

    def test_thread_formatter_caps_huge_fallback_updates(self):
        # Generate 15 distinct sections
        huge_analysis = "\n\n".join([f"🎯 Section {i}:\n• Bullet point for section {i}" for i in range(1, 16)])
        thread = XThreadFormatter.format_thread(
            event=self.event,
            analysis_en=huge_analysis,
            patch_version="1.41.9.9",
            telegram_channel_url="https://t.me/cs2_alarm",
            max_body_tweets=5,
        )

        # Thread must not exceed 1 root + 5 body + 1 final = 7 tweets max
        self.assertLessEqual(len(thread), 7)

    async def test_publisher_dry_run_mode(self):
        settings = MagicMock(spec=AppSettings)
        settings.x_enabled = True
        settings.x_dry_run = True
        settings.x_api_key = None
        settings.x_api_secret = None
        settings.x_access_token = None
        settings.x_access_token_secret = None

        publisher = XPublisherService(settings)
        self.assertTrue(publisher.is_dry_run)
        self.assertFalse(publisher.is_configured)

        thread = ["[1/2] Test tweet", "[2/2] Final tweet"]
        result = await publisher.publish_thread(thread)

        self.assertEqual(len(result), 2)
        self.assertEqual(result, ["mock_x_tweet_1", "mock_x_tweet_2"])

    async def test_publisher_disabled_mode(self):
        settings = MagicMock(spec=AppSettings)
        settings.x_enabled = False

        publisher = XPublisherService(settings)
        result = await publisher.publish_thread(["Tweet 1"])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
