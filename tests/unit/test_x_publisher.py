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
        self.assertIn("link in bio", thread[-1].lower())
        self.assertNotIn("github.com", thread[-1])
        self.assertNotIn("https://t.me", thread[-1])  # Excluded raw URL to prevent X URL tax & penalties
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

        # Since curated[-1] has <= 190 chars, CTA is embedded directly into it
        self.assertEqual(len(thread), 3)  # 1 root + 2 curated (embedded CTA in tweet 2)
        self.assertIn("Inferno and Vertigo", thread[1])
        self.assertIn("knife models", thread[2])
        self.assertIn("link in bio", thread[2].lower())

    def test_thread_formatter_cta_separate_when_last_tweet_is_full(self):
        # A long last tweet (> 190 chars) should push CTA to a dedicated tweet
        long_tweet = "🔎 " + ("Extremely long datamining finding detailing byte changes and shader graphs " * 3)
        curated = [
            "🎯 Quick highlight.",
            long_tweet,
        ]
        thread = XThreadFormatter.format_thread(
            event=self.event,
            analysis_en="Full text",
            patch_version="1.41.9.8",
            telegram_channel_url="https://t.me/cs2_alarm",
            curated_tweets=curated,
        )

        self.assertEqual(len(thread), 4)  # 1 root + 2 curated + 1 separate final
        self.assertIn("link in bio", thread[3].lower())

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

    def test_twitter_weighted_length(self):
        from app.notifications.x_formatter import twitter_weighted_length

        # ASCII
        self.assertEqual(twitter_weighted_length("Hello CS2"), 9)
        # Emojis count as 2
        self.assertEqual(twitter_weighted_length("⚡ CS2"), 6)
        # URL counts as fixed 23
        self.assertEqual(twitter_weighted_length("Join: https://t.me/cs2_alarm"), 6 + 23)

    def test_sync_publish_preserves_posted_ids_on_partial_failure(self):
        settings = MagicMock(spec=AppSettings)
        settings.x_enabled = True
        settings.x_dry_run = False
        settings.x_api_key = "key"
        settings.x_api_secret = "secret"
        settings.x_access_token = "token"
        settings.x_access_token_secret = "token_secret"

        publisher = XPublisherService(settings)

        # Mock tweepy client
        with patch("tweepy.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            # Root tweet succeeds, 2nd tweet succeeds, 3rd fails
            mock_client.create_tweet.side_effect = [
                MagicMock(data={"id": "tweet_1"}),
                MagicMock(data={"id": "tweet_2"}),
                Exception("API rate limit or connection error"),
            ]

            posted = publisher._sync_publish(["Post 1", "Post 2", "Post 3"])

            # Must return the 2 successfully created tweets, not empty list!
            self.assertEqual(posted, ["tweet_1", "tweet_2"])

    def test_sync_publish_resumes_from_reply_to_tweet_id(self):
        settings = MagicMock(spec=AppSettings)
        settings.x_enabled = True
        settings.x_dry_run = False
        settings.x_api_key = "key"
        settings.x_api_secret = "secret"
        settings.x_access_token = "token"
        settings.x_access_token_secret = "token_secret"

        publisher = XPublisherService(settings)

        with patch("tweepy.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            mock_client.create_tweet.side_effect = [
                MagicMock(data={"id": "tweet_3"}),
                MagicMock(data={"id": "tweet_4"}),
            ]

            posted = publisher._sync_publish(
                thread=["Post 3", "Post 4"],
                reply_to_tweet_id="tweet_2",
            )

            self.assertEqual(posted, ["tweet_3", "tweet_4"])
            # Verify calls: Post 3 must reply to tweet_2, Post 4 must reply to tweet_3
            mock_client.create_tweet.assert_any_call(text="Post 3", in_reply_to_tweet_id="tweet_2")
            mock_client.create_tweet.assert_any_call(text="Post 4", in_reply_to_tweet_id="tweet_3")

    async def test_update_repository_x_thread_info_and_deduplication(self):
        from app.repositories.update_repository import UpdateRepository
        from app.models.update import Update

        update_id = uuid.uuid4()
        mock_session = MagicMock()

        # 1. Update with no X events
        empty_update = MagicMock(spec=Update)
        empty_update.id = update_id
        empty_update.timeline = {"events": []}

        repo = UpdateRepository(mock_session)
        with patch.object(repo, "get_by_id", return_value=empty_update):
            info = await repo.get_x_thread_info(update_id)
            self.assertIsNone(info)
            self.assertFalse(await repo.is_x_thread_published(update_id))

        # 2. Update with partial X event
        partial_update = MagicMock(spec=Update)
        partial_update.id = update_id
        partial_update.timeline = {
            "events": [
                {
                    "type": "x_thread_partial",
                    "metadata": {
                        "tweet_ids": ["tweet_1", "tweet_2"],
                        "root_tweet_id": "tweet_1",
                        "total_tweets": 4,
                    },
                }
            ]
        }
        with patch.object(repo, "get_by_id", return_value=partial_update):
            info = await repo.get_x_thread_info(update_id)
            self.assertIsNotNone(info)
            self.assertEqual(info["status"], "partial")
            self.assertEqual(info["tweet_ids"], ["tweet_1", "tweet_2"])
            self.assertEqual(info["last_tweet_id"], "tweet_2")
            # Must NOT be considered fully published
            self.assertFalse(await repo.is_x_thread_published(update_id))

        # 3. Update with fully completed X event
        completed_update = MagicMock(spec=Update)
        completed_update.id = update_id
        completed_update.timeline = {
            "events": [
                {
                    "type": "x_thread_partial",
                    "metadata": {"tweet_ids": ["tweet_1"]},
                },
                {
                    "type": "x_thread_published",
                    "metadata": {
                        "tweet_ids": ["tweet_1", "tweet_2", "tweet_3", "tweet_4"],
                        "root_tweet_id": "tweet_1",
                        "total_tweets": 4,
                    },
                },
            ]
        }
        with patch.object(repo, "get_by_id", return_value=completed_update):
            info = await repo.get_x_thread_info(update_id)
            self.assertIsNotNone(info)
            self.assertEqual(info["status"], "published")
            self.assertEqual(len(info["tweet_ids"]), 4)
            # Must be recognized as fully published
            self.assertTrue(await repo.is_x_thread_published(update_id))

    def test_format_single_post_for_x_premium(self):
        analysis = """🎯 <b>Key Highlights:</b>
• <b>Cobblestone:</b> Fixed walkable ledges and empty skybox.
• <b>Inferno:</b> Closed grenade exploit from church to dark.

🔎 <b>Game File Discoveries:</b>
• <b>AWP:</b> Added silent reload animation."""

        post = XThreadFormatter.format_single_post(
            event=self.event,
            analysis_en=analysis,
            patch_version="1.42.0.0",
        )

        self.assertIn("🚨 CS2 Update • 1.42.0.0 is LIVE!", post)
        self.assertIn("Build ID: 26598758", post)
        self.assertIn("🎯 Key Highlights:", post)
        self.assertIn("• Cobblestone: Fixed walkable ledges and empty skybox.", post)
        self.assertIn("• Inferno: Closed grenade exploit from church to dark.", post)
        self.assertIn("🔎 Game File Discoveries:", post)
        self.assertIn("• AWP: Added silent reload animation.", post)
        self.assertIn("link in bio", post.lower())
        self.assertNotIn("https://", post)  # No raw external links in body
        self.assertIn("#CS2", post)
        self.assertIn("#CS2Update", post)


if __name__ == "__main__":
    unittest.main()
