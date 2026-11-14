"""
CS2 Instant Alert — X (Twitter) Thread Formatter.

Converts English update analysis into an organic, multi-tweet thread
strictly respecting Twitter character limits (280 chars) without mid-sentence cuts.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.events.types import UpdateDetectedEvent
from app.utils.datetime import format_date

MAX_TWEET_LENGTH = 275  # Safe boundary below 280 for t.co URLs and emoji weights


def clean_html(text: str) -> str:
    """Strip HTML tags while preserving line breaks and text content."""
    # Convert <a href="url">text</a> -> text: url
    text = re.sub(r'<a\s+href="([^"]+)">([^<]+)</a>', r"\2: \1", text)
    # Strip basic tags
    text = re.sub(r"</?(?:b|i|code|strong|em|p|span)>", "", text)
    # Convert HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#8205;", "")
    return text.strip()


class XThreadFormatter:
    """Formats CS2 update events into an organic X (Twitter) thread."""

    @classmethod
    def format_thread(
        cls,
        event: UpdateDetectedEvent,
        analysis_en: str,
        patch_version: str | None = None,
        patch_url: str | None = None,
        telegram_channel_url: str = "https://t.me/cs2_alarm",
        timezone: str = "UTC",
    ) -> list[str]:
        """
        Build a list of tweet texts representing the complete thread.

        Tweet 1: Root announcement with hook, build, and thread marker (banner attaches here)
        Tweet 2..N-1: Key highlights and datamining findings split by section & bullet
        Tweet N: Sources, Telegram community link, and hashtags
        """
        date_str = format_date(event.detected_at, timezone)
        version_part = f"• {patch_version} " if patch_version else ""

        # ─── 1. Tweet 1: Root Tweet ───
        tweet_1_raw = (
            f"🚨 CS2 Update {version_part}is LIVE!\n\n"
            f"📅 Date: {date_str}\n"
            f"📦 Build ID: {event.build_id}\n\n"
            f"Full breakdown & datamining thread below 🧵👇"
        )

        # ─── 2. Body Tweets from analysis_en ───
        body_tweets = cls._split_analysis_into_tweets(analysis_en)

        # ─── 3. Final Tweet: Sources & Community ───
        final_lines = ["🔗 Details & Sources:\n"]
        if patch_url:
            final_lines.append(f"🌐 File Diff: {patch_url}")
        if telegram_channel_url:
            final_lines.append(f"👥 English Community: {telegram_channel_url}")
        final_lines.append("\n#CS2 #CounterStrike2 #CS2Update")
        tweet_final_raw = "\n".join(final_lines)

        raw_thread = [tweet_1_raw] + body_tweets + [tweet_final_raw]
        total = len(raw_thread)

        # ─── 4. Apply Numbering [1/N] ───
        numbered_thread: list[str] = []
        for idx, tweet in enumerate(raw_thread, start=1):
            prefix = f"[{idx}/{total}] "
            numbered_text = f"{prefix}{tweet}"
            # Safety check: if text slightly exceeds max, trim gracefully at word boundary
            if len(numbered_text) > 280:
                cut = numbered_text.rfind(" ", 0, 275)
                numbered_text = numbered_text[:cut] + "…" if cut > 100 else numbered_text[:279]
            numbered_thread.append(numbered_text)

        return numbered_thread

    @classmethod
    def _split_analysis_into_tweets(cls, analysis_html: str) -> list[str]:
        """Splits HTML analysis into organic tweets grouped by section and bullets."""
        clean_text = clean_html(analysis_html)
        if not clean_text:
            return ["⚙️ Technical binary update without gameplay, settings, or UI changes."]

        # Break text into sections by headers (e.g. 🎯 Key Highlights:, 🔎 Game File Discoveries:)
        lines = clean_text.splitlines()
        sections: list[tuple[str, list[str]]] = []
        current_header = ""
        current_bullets: list[str] = []

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Header detection (starts with an emoji or ends with colon without bullet)
            is_header = any(line_str.startswith(icon) for icon in ("🎯", "🔎", "🛠", "🔮", "⚙️")) or (
                line_str.endswith(":") and not line_str.startswith("•")
            )

            if is_header:
                if current_header or current_bullets:
                    sections.append((current_header, current_bullets))
                current_header = line_str
                current_bullets = []
            elif line_str.startswith("•"):
                current_bullets.append(line_str)
            else:
                # Regular descriptive sentence
                if current_bullets:
                    current_bullets[-1] += f" {line_str}"
                elif current_header:
                    current_bullets.append(f"• {line_str}")
                else:
                    current_header = line_str

        if current_header or current_bullets:
            sections.append((current_header, current_bullets))

        tweets: list[str] = []
        target_max = 265  # Leaves room for [X/Y] prefix

        for header, bullets in sections:
            if not bullets:
                if header:
                    tweets.append(header)
                continue

            current_tweet = f"{header}\n" if header else ""

            for bullet in bullets:
                # If bullet itself is massive, trim or add
                candidate = f"{current_tweet}\n{bullet}".strip()
                if len(candidate) <= target_max:
                    current_tweet = candidate
                else:
                    # Flush previous tweet if non-empty
                    if current_tweet.strip() and current_tweet.strip() != header:
                        tweets.append(current_tweet.strip())
                    # Start new tweet with section continuation
                    clean_h = header.rstrip(":")
                    cont_header = f"{clean_h} (cont.):" if header else ""
                    new_candidate = f"{cont_header}\n{bullet}".strip()
                    if len(new_candidate) <= target_max:
                        current_tweet = new_candidate
                    else:
                        # Single bullet is longer than target_max, truncate at word boundary
                        cut = new_candidate.rfind(" ", 0, target_max - 2)
                        tweets.append(new_candidate[:cut] + "…")
                        current_tweet = f"…{new_candidate[cut:]}".strip()

            if current_tweet.strip() and current_tweet.strip() != header:
                tweets.append(current_tweet.strip())

        return tweets
