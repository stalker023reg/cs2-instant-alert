"""
CS2 Instant Alert — Steam News Fetcher.

Fetches official patch notes from Steam News API and Steam Community RSS for CS2 (AppID 730).
Filters news items published within the update detection time window.
Includes aggressive cache-busting and dual-source fallback (API + RSS) to avoid Akamai edge-caching delays.
"""

from __future__ import annotations

import email.utils
import re
import time
import xml.etree.ElementTree as ET
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
        Query Steam News API and fallback to Steam Community RSS to return matching
        patch notes published within the specified timeframe around `detected_at`.

        Returns:
            SteamNewsItem if a relevant announcement is found, otherwise None.
        """
        window_start = detected_at - timedelta(minutes=min_window_minutes_before)
        window_end = datetime.now(UTC) + timedelta(minutes=max_window_minutes_after)

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                # 1. Primary: Steam Web API with cache-busting timestamp and no-cache headers
                item = await self._fetch_from_webapi(client, window_start, window_end)
                if item:
                    return item

                # 2. Secondary Fallback: Steam Community RSS feed (immediate propagation)
                rss_item = await self._fetch_from_rss(client, window_start, window_end)
                if rss_item:
                    return rss_item

        except httpx.TimeoutException:
            await logger.awarning("steam_news_fetch_timeout")
        except Exception as e:
            await logger.aerror("steam_news_fetch_error", error=str(e), exc_info=True)

        return None

    async def _fetch_from_webapi(
        self,
        client: httpx.AsyncClient,
        window_start: datetime,
        window_end: datetime,
    ) -> SteamNewsItem | None:
        """Fetch patch notes from ISteamNews/GetNewsForApp/v2 with cache busting."""
        cb = int(time.time())
        url = f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={CS2_APP_ID}&count=15&_cb={cb}"
        headers = {
            "User-Agent": "CS2-Instant-Alert-Bot/1.0",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }

        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            await logger.awarning("steam_news_fetch_failed", status_code=resp.status_code)
            return None

        data = resp.json()
        newsitems = data.get("appnews", {}).get("newsitems", [])

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

        return None

    async def _fetch_from_rss(
        self,
        client: httpx.AsyncClient,
        window_start: datetime,
        window_end: datetime,
    ) -> SteamNewsItem | None:
        """Fetch patch notes from store.steampowered.com/feeds/news/app RSS feed."""
        cb = int(time.time())
        rss_url = f"https://store.steampowered.com/feeds/news/app/{CS2_APP_ID}/?_cb={cb}"
        headers = {
            "User-Agent": "CS2-Instant-Alert-Bot/1.0",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }

        try:
            resp = await client.get(rss_url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                await logger.awarning("steam_rss_fetch_failed", status_code=resp.status_code)
                return None

            root = ET.fromstring(resp.text)
            for item in root.findall("./channel/item"):
                title = item.findtext("title") or ""
                pub_date_str = item.findtext("pubDate") or ""
                if not pub_date_str:
                    continue

                try:
                    item_date = email.utils.parsedate_to_datetime(pub_date_str)
                    if item_date.tzinfo is None:
                        item_date = item_date.replace(tzinfo=UTC)
                except Exception:
                    continue

                if not (window_start <= item_date <= window_end):
                    continue

                is_official = (
                    "update" in title.lower()
                    or "release notes" in title.lower()
                    or "patch" in title.lower()
                )
                if not is_official:
                    continue

                link = item.findtext("link") or ""
                guid = item.findtext("guid") or ""
                gid = guid.rstrip("/").split("/")[-1] if guid else ""
                contents = item.findtext("description") or ""

                await logger.ainfo(
                    "steam_rss_patchnotes_matched",
                    gid=gid,
                    title=title,
                    date=item_date.isoformat(),
                )
                return SteamNewsItem(
                    gid=gid,
                    title=title,
                    contents=contents,
                    url=link or (f"https://steamcommunity.com/games/{CS2_APP_ID}/announcements/detail/{gid}" if gid else ""),
                    date=item_date,
                    feedname="steam_community_announcements",
                )
        except Exception as e:
            await logger.awarning("steam_rss_parse_error", error=str(e))
            return None

        return None
