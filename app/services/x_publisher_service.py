"""
CS2 Instant Alert — X (Twitter) Publisher Service.

Delivers formatted multi-tweet threads to X using Twitter API v2.
Supports dry-run testing and non-blocking asynchronous execution.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.core.logging import get_logger

logger = get_logger("x_publisher")


class XPublisherService:
    """Publishes CS2 update threads to X (Twitter)."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        x_api_key = getattr(settings, "x_api_key", None)
        x_api_secret = getattr(settings, "x_api_secret", None)
        x_access_token = getattr(settings, "x_access_token", None)
        x_access_token_secret = getattr(settings, "x_access_token_secret", None)

        self.api_key = (
            x_api_key.get_secret_value()
            if x_api_key and hasattr(x_api_key, "get_secret_value")
            else str(x_api_key or "")
        )
        self.api_secret = (
            x_api_secret.get_secret_value()
            if x_api_secret and hasattr(x_api_secret, "get_secret_value")
            else str(x_api_secret or "")
        )
        self.access_token = (
            x_access_token.get_secret_value()
            if x_access_token and hasattr(x_access_token, "get_secret_value")
            else str(x_access_token or "")
        )
        self.access_token_secret = (
            x_access_token_secret.get_secret_value()
            if x_access_token_secret and hasattr(x_access_token_secret, "get_secret_value")
            else str(x_access_token_secret or "")
        )

    @property
    def is_configured(self) -> bool:
        """Check if all required OAuth1 credentials are provided."""
        return bool(
            self.api_key
            and self.api_secret
            and self.access_token
            and self.access_token_secret
        )

    @property
    def is_dry_run(self) -> bool:
        """Dry-run mode is active if explicitly set or if keys are missing."""
        return self.settings.x_dry_run or not self.is_configured

    async def publish_thread(
        self,
        thread: list[str],
        banner_path: Path | str | None = None,
        reply_to_tweet_id: str | None = None,
    ) -> list[str]:
        """
        Publish a multi-tweet thread sequentially.
        If reply_to_tweet_id is provided, resumes publishing the thread as replies
        to that tweet without posting a new root tweet or re-uploading media.

        Returns a list of published tweet IDs (or mock IDs in dry-run mode).
        Never raises exceptions that disrupt the main notification flow.
        """
        if not self.settings.x_enabled:
            return []

        if not thread:
            return []

        # ─── Dry-Run Mode ───
        if self.is_dry_run:
            prefix = "mock_x_reply" if reply_to_tweet_id else "mock_x_tweet"
            mock_ids = [f"{prefix}_{i}" for i in range(1, len(thread) + 1)]
            await logger.ainfo(
                "x_publish_dry_run",
                tweet_count=len(thread),
                is_configured=self.is_configured,
                is_resuming=bool(reply_to_tweet_id),
                reply_to_tweet_id=reply_to_tweet_id,
                root_preview=thread[0][:100],
            )
            return mock_ids

        # ─── Live Mode ───
        try:
            return await asyncio.to_thread(self._sync_publish, thread, banner_path, reply_to_tweet_id)
        except Exception as e:
            await logger.aerror("x_publish_failed", error=str(e), exc_info=True)
            return []

    def _sync_publish(
        self,
        thread: list[str],
        banner_path: Path | str | None = None,
        reply_to_tweet_id: str | None = None,
    ) -> list[str]:
        """Synchronous Tweepy publishing executed in a worker thread."""
        import tweepy

        # Tweepy Client for v2 Tweets
        client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
        )

        posted_ids: list[str] = []

        # If resuming from an existing tweet in a broken thread:
        if reply_to_tweet_id:
            prev_id = reply_to_tweet_id
            for idx, tweet_text in enumerate(thread, start=1):
                try:
                    reply_resp = client.create_tweet(
                        text=tweet_text,
                        in_reply_to_tweet_id=prev_id,
                    )
                    prev_id = str(reply_resp.data["id"])
                    posted_ids.append(prev_id)
                except Exception as chain_err:
                    print(f"[XPublisher] Partial thread break while resuming at {idx}/{len(thread)}: {chain_err}")
                    break
            return posted_ids

        # Fresh Thread:
        # 1. Media Upload for Root Tweet (v1.1 API)
        media_ids: list[str] | None = None
        if banner_path and os.path.exists(banner_path):
            try:
                auth = tweepy.OAuth1UserHandler(
                    self.api_key,
                    self.api_secret,
                    self.access_token,
                    self.access_token_secret,
                )
                api = tweepy.API(auth)
                media = api.media_upload(filename=str(banner_path))
                media_ids = [str(media.media_id)]
            except Exception as media_err:
                # Log and continue without media if upload fails
                print(f"[XPublisher] Media upload failed: {media_err}")
                media_ids = None

        # 2. Post Root Tweet
        root_resp = client.create_tweet(text=thread[0], media_ids=media_ids)
        root_id = str(root_resp.data["id"])
        posted_ids.append(root_id)
        prev_id = root_id

        # 3. Post Reply Chain
        for idx, tweet_text in enumerate(thread[1:], start=2):
            try:
                reply_resp = client.create_tweet(
                    text=tweet_text,
                    in_reply_to_tweet_id=prev_id,
                )
                prev_id = str(reply_resp.data["id"])
                posted_ids.append(prev_id)
            except Exception as chain_err:
                print(f"[XPublisher] Partial thread break at {idx}/{len(thread)}: {chain_err}")
                break

        return posted_ids
