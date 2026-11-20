"""
CS2 Instant Alert — SteamCMD API Fallback Monitor.

Fallback monitoring source using the public SteamCMD API
(https://api.steamcmd.net).  Unlike PICS, this endpoint does NOT require
authentication and always returns the current public build_id.

Used automatically when the primary PICS source fails (e.g., anonymous
login token restriction by Valve).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.core.logging import get_logger
from app.steam.monitor import SteamMonitor
from app.steam.types import AppUpdateData, BranchInfo, SteamSource

logger = get_logger("steam")


class SteamCMDFallbackMonitor(SteamMonitor):
    """
    Fetches app info from the public SteamCMD API as a PICS fallback.

    Endpoint: GET https://api.steamcmd.net/v1/info/<app_id>
    Returns branches with build_id — enough for update detection.
    """

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=10.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        self._base_url = "https://api.steamcmd.net/v1/info"

    @property
    def source_name(self) -> SteamSource:
        # Report as PICS so the downstream processing pipeline works
        # identically — this is a transparent replacement, not a new source.
        return SteamSource.PICS

    async def get_app_data(self, app_id: int) -> AppUpdateData | None:
        """Fetch app info from SteamCMD public API."""
        url = f"{self._base_url}/{app_id}"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            await logger.awarning(
                "steamcmd_fallback_fetch_failed",
                app_id=app_id,
                error=str(e),
            )
            return None

        # Navigate: data -> <app_id> -> depots -> branches -> public -> buildid
        app_data = data.get("data", {}).get(str(app_id), {})
        if not app_data:
            await logger.awarning("steamcmd_fallback_no_data", app_id=app_id)
            return None

        depots = app_data.get("depots", {})
        branches_data = depots.get("branches", {})

        change_number = app_data.get("_change_number", app_data.get("changenumber"))
        if change_number is not None:
            try:
                change_number = int(change_number)
            except (ValueError, TypeError):
                change_number = None

        result = AppUpdateData(
            app_id=app_id,
            source=self.source_name,
            checked_at=datetime.now(UTC),
            change_number=change_number,
            raw_payload=app_data,
        )

        for branch_name, branch_info in branches_data.items():
            if not isinstance(branch_info, dict):
                continue

            build_id = branch_info.get("buildid")
            if not build_id:
                continue

            time_updated_raw = branch_info.get("timeupdated")
            time_updated = (
                datetime.fromtimestamp(int(time_updated_raw), tz=UTC)
                if time_updated_raw
                else None
            )

            result.branches[branch_name] = BranchInfo(
                name=branch_name,
                build_id=str(build_id),
                time_updated=time_updated,
                pwd_required=bool(int(branch_info.get("pwdrequired", 0))),
                description=branch_info.get("description"),
            )

        if not result.get_public_build_id():
            await logger.awarning(
                "steamcmd_fallback_no_public_branch", app_id=app_id
            )
            return None

        return result

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
