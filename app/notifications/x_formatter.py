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


def twitter_weighted_length(text: str) -> int:
    """
    Computes text length according to official Twitter / X text counting rules:
    - Standard ASCII characters: 1 weight
    - Emojis and extended Unicode codepoints: 2 weight
    - URLs (http:// or https://): 23 fixed weight (t.co transform)
    """
    # Replace URLs with 23 placeholder characters
    text_no_urls = re.sub(r"https?://\S+", "X" * 23, text)
    weight = 0
    for char in text_no_urls:
        code = ord(char)
        if code > 4351 or (0x1F000 <= code <= 0x1FFFF):
            weight += 2
        else:
            weight += 1
    return weight


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
        curated_tweets: list[str] | None = None,
        max_body_tweets: int = 8,
    ) -> list[str]:
        """
        Build a list of tweet texts representing the complete thread.

        Tweet 1: Root announcement with hook, build, and thread marker (banner attaches here)
        Tweet 2..N: Key highlights and datamining findings (AI-curated or smartly split)
        Last Tweet: Integrates CTA link to Telegram community ("Want alerts earlier?...")
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

        # ─── 2. Body Tweets (Curated by Gemini or algorithmic fallback) ───
        if curated_tweets and len(curated_tweets) > 0:
            cleaned_curated: list[str] = []
            for t in curated_tweets:
                c = clean_html(t)
                if c:
                    cleaned_curated.append(c)
            body_tweets = cleaned_curated[:max_body_tweets]
        else:
            body_tweets = cls._split_analysis_into_tweets(analysis_en, max_tweets=max_body_tweets)

        # ─── 3. Embed Telegram CTA into the last tweet (or append closing tweet if full) ───
        cta_suffix = (
            "\n\n⚡ Want instant CS2 alerts earlier? Link in bio!\n"
            "#CS2 #CounterStrike2 #CS2Update"
        )

        if body_tweets and (twitter_weighted_length(body_tweets[-1]) <= 190):
            body_tweets[-1] = body_tweets[-1] + cta_suffix
            raw_thread = [tweet_1_raw] + body_tweets
        else:
            tweet_final_raw = (
                "⚡ Want instant CS2 alerts earlier?\n"
                "👉 Join our Telegram community (link in bio)!\n\n"
                "#CS2 #CounterStrike2 #CS2Update"
            )
            raw_thread = [tweet_1_raw] + body_tweets + [tweet_final_raw]

        total = len(raw_thread)

        # ─── 4. Apply Numbering [1/N] and 280-char safety bounds ───
        numbered_thread: list[str] = []
        for idx, tweet in enumerate(raw_thread, start=1):
            prefix = f"[{idx}/{total}] "
            numbered_text = f"{prefix}{tweet}"
            # Safety check: if weighted text exceeds 280, trim gracefully at word boundary
            while twitter_weighted_length(numbered_text) > 280:
                cut = numbered_text.rfind(" ", 0, len(numbered_text) - 5)
                if cut > 20:
                    numbered_text = numbered_text[:cut] + "…"
                else:
                    numbered_text = numbered_text[:-5] + "…"
                    break
            numbered_thread.append(numbered_text)

        return numbered_thread

    @classmethod
    def _split_analysis_into_tweets(cls, analysis_html: str, max_tweets: int = 8) -> list[str]:
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
                if twitter_weighted_length(candidate) <= target_max:
                    current_tweet = candidate
                else:
                    # Flush previous tweet if non-empty
                    if current_tweet.strip() and current_tweet.strip() != header:
                        tweets.append(current_tweet.strip())
                    # Start new tweet with section continuation
                    clean_h = header.rstrip(":")
                    cont_header = f"{clean_h} (cont.):" if header else ""
                    new_candidate = f"{cont_header}\n{bullet}".strip()
                    if twitter_weighted_length(new_candidate) <= target_max:
                        current_tweet = new_candidate
                    else:
                        # Single bullet is longer than target_max, truncate at word boundary
                        cut = new_candidate.rfind(" ", 0, min(len(new_candidate), target_max - 2))
                        if cut > 20:
                            tweets.append(new_candidate[:cut] + "…")
                            current_tweet = f"…{new_candidate[cut:]}".strip()
                        else:
                            # Trim using weighted length safely
                            trimmed = new_candidate
                            while twitter_weighted_length(trimmed) > target_max and len(trimmed) > 5:
                                trimmed = trimmed[:-5] + "…"
                            tweets.append(trimmed)
                            current_tweet = ""

            if current_tweet.strip() and current_tweet.strip() != header:
                tweets.append(current_tweet.strip())

        if len(tweets) > max_tweets:
            capped = tweets[: max_tweets - 1]
            capped.append("🔎 Additional minor adjustments, workshop fixes & full logs in our community.")
            return capped

        return tweets
