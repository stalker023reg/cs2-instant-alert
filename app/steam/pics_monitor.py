"""
CS2 Instant Alert — PICS Monitor.

Primary monitoring source using Steam's Product Information
Catalog Service (PICS) via the Steam Client connection.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.steam.client import AsyncSteamClient, SteamConnectionError
from app.steam.monitor import SteamMonitor
from app.steam.types import AppUpdateData, BranchInfo, DepotInfo, SteamSource
from app.utils.retry import async_retry

logger = get_logger("steam")


class PICSMonitor(SteamMonitor):
    """
    Monitors Steam updates using the PICS network.
    This is the fastest and most reliable source of updates.
    """

    def __init__(self, steam_client: AsyncSteamClient) -> None:
        self.client = steam_client

    @property
    def source_name(self) -> SteamSource:
        return SteamSource.PICS

    @async_retry(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(SteamConnectionError,),
    )
    async def get_app_data(self, app_id: int) -> AppUpdateData | None:
        """
        Fetch app info from PICS and parse it into standardized format.
        """
        try:
            info = await self.client.get_product_info(apps=[app_id])
        except SteamConnectionError as e:
            await logger.awarning("pics_fetch_failed", app_id=app_id, error=str(e))
            raise  # Retry will catch this

        if not info or "apps" not in info or app_id not in info["apps"]:
            await logger.awarning("pics_app_not_found", app_id=app_id)
            return None

        app_data = info["apps"][app_id]

        # The steam library may return the data directly or wrapped in 'appinfo'
        appinfo = app_data.get("appinfo", app_data)

        # Check if it's a completely empty/hidden response
        if "_missing_token" in app_data and len(app_data) <= 5: # just meta keys
            await logger.awarning("pics_app_hidden_or_missing", app_id=app_id)
            return None

        change_number = app_data.get("changenumber", app_data.get("_change_number"))

        depots_data = appinfo.get("depots", {})
        branches_data = appinfo.get("branches", depots_data.get("branches", {}))

        result = AppUpdateData(
            app_id=app_id,
            source=self.source_name,
            checked_at=datetime.now(UTC),
            change_number=change_number,
            raw_payload=appinfo,
        )

        # Parse branches
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

        # Parse depots
        for depot_id_str, depot_info in depots_data.items():
            # Skip non-numeric keys like 'branches'
            if not depot_id_str.isdigit() or not isinstance(depot_info, dict):
                continue

            depot_id = int(depot_id_str)
            manifests = depot_info.get("manifests", {})

            # Usually we care about the public branch manifest
            public_manifest = manifests.get("public", {})
            if isinstance(public_manifest, dict):
                manifest_id = public_manifest.get("gid")
                size_bytes = public_manifest.get("size")

                result.depots[depot_id] = DepotInfo(
                    depot_id=depot_id,
                    name=depot_info.get("name"),
                    manifest_id=str(manifest_id) if manifest_id else None,
                    size_bytes=int(size_bytes) if size_bytes else None,
                )

        return result
