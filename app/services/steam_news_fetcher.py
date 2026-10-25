"""
CS2 Instant Alert — Steam News Fetcher.

Fetches official patch notes from Steam News API for CS2 (AppID 730).
Filters news items published within the update detection time window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.core.constants import CS2_APP_ID
from app.core.logging import get_logger

logger = get_logger("system")


@dataclass
class SteamNewsItem:
    """Represents a validated official patch notes news item."""

    gid: str
    title: str
    contents: str
    url: str
    date: datetime
    feedname: str


class SteamNewsFetcher:
    """Fetches official Steam News / Patch Notes for Counter-Strike 2."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def fetch_latest_patchnotes(
        self,
        detected_at: datetime,
        min_window_minutes_before: int = 15,
        max_window_minutes_after: int = 25,
    ) -> SteamNewsItem | None:
        """
        Query Steam News API and return the matching patch notes if published
        within the specified timeframe around `detected_at`.

        Returns:
            SteamNewsItem if a relevant announcement is found, otherwise None.
        """
        url = f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={CS2_APP_ID}&count=5"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                headers = {"User-Agent": "CS2-Instant-Alert-Bot/1.0"}
                resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    await logger.awarning(
                        "steam_news_fetch_failed",
                        status_code=resp.status_code,
                    )
                    return None

                data = resp.json()
                newsitems = data.get("appnews", {}).get("newsitems", [])

                window_start = detected_at - timedelta(minutes=min_window_minutes_before)
                window_end = datetime.now(UTC) + timedelta(minutes=max_window_minutes_after)

                for item in newsitems:
                    feedname = item.get("feedname", "")
                    tags = item.get("tags", []) or []
                    title = item.get("title", "")
                    raw_date = item.get("date", 0)

                    item_date = datetime.fromtimestamp(raw_date, tz=UTC)

                    # Check time window
                    if not (window_start <= item_date <= window_end):
                        continue

                    # Filter: official announcement / patchnotes
                    is_official = (
                        feedname == "steam_community_announcements"
                        or "patchnotes" in tags
                        or "release notes" in title.lower()
                        or "update" in title.lower()
                    )

                    if not is_official:
                        continue

                    gid = str(item.get("gid", ""))
                    patch_url = (
                        f"https://steamcommunity.com/games/{CS2_APP_ID}/announcements/detail/{gid}"
                        if gid
                        else item.get("url", "")
                    )

                    raw_contents = item.get("contents", "")

                    await logger.ainfo(
                        "steam_news_patchnotes_matched",
                        gid=gid,
                        title=title,
                        date=item_date.isoformat(),
                    )

                    return SteamNewsItem(
                        gid=gid,
                        title=title,
                        contents=raw_contents,
                        url=patch_url,
                        date=item_date,
                        feedname=feedname,
                    )

        except httpx.TimeoutException:
            await logger.awarning("steam_news_fetch_timeout")
        except Exception as e:
            await logger.aerror("steam_news_fetch_error", error=str(e), exc_info=True)

        return None
