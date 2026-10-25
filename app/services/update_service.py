"""
CS2 Instant Alert — Update Service.

Handles business logic for detecting new updates, saving them
to the database, and emitting events.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.bus import EventBus
from app.events.types import UpdateDetectedEvent
from app.models.build_history import BuildHistory
from app.models.steam_app_state import SteamAppState
from app.models.update import Update
from app.repositories.build_history_repository import BuildHistoryRepository
from app.repositories.steam_state_repository import SteamStateRepository
from app.repositories.update_repository import UpdateRepository
from app.steam.types import AppUpdateData

logger = get_logger("system")


class UpdateService:
    """Service for handling game updates."""

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBus,
    ) -> None:
        self.session = session
        self.event_bus = event_bus
        self.update_repo = UpdateRepository(session)
        self.history_repo = BuildHistoryRepository(session)
        self.state_repo = SteamStateRepository(session)

    async def process_steam_data(
        self,
        game_id: uuid.UUID,
        app_state: SteamAppState,
        data: AppUpdateData,
    ) -> bool:
        """
        Process incoming Steam data, detect if there is a new update,
        save to DB, and emit events.
        
        Returns:
            True if a new update was detected, False otherwise.
        """
        public_build_id = data.get_public_build_id()
        if not public_build_id:
            # We don't have public branch info
            return False

        previous_build_id = app_state.last_build_id

        # Check if build ID changed
        is_new_update = (
            previous_build_id is not None
            and public_build_id != previous_build_id
        )
        is_first_seen = previous_build_id is None

        now = datetime.now(UTC)
        
        public_branch = data.branches.get("public")
        if public_branch and public_branch.time_updated:
            new_update_time = public_branch.time_updated
        elif is_new_update or is_first_seen:
            new_update_time = now
        else:
            new_update_time = app_state.last_update_at

        # Update build history regardless
        await self._record_build_history(game_id, public_build_id, data, now)

        # Update app state
        await self.state_repo.update_state(
            game_id,
            build_id=public_build_id,
            change_number=data.change_number,
            check_time=now,
            update_time=new_update_time,
        )

        if is_new_update:
            await self._handle_new_update(
                game_id,
                previous_build_id,
                public_build_id,
                data,
                now,
            )
            return True

        return False

    async def _record_build_history(
        self,
        game_id: uuid.UUID,
        build_id: str,
        data: AppUpdateData,
        now: datetime,
    ) -> None:
        """Record or update build history."""
        existing = await self.history_repo.get_by_build_id(game_id, build_id, "public")

        if existing:
            await self.history_repo.update_by_id(existing.id, last_seen_at=now)
        else:
            new_history = BuildHistory(
                game_id=game_id,
                build_id=build_id,
                branch="public",
                change_number=data.change_number,
                first_seen_at=now,
                last_seen_at=now,
            )
            await self.history_repo.create(new_history)

    async def _handle_new_update(
        self,
        game_id: uuid.UUID,
        old_build_id: str | None,
        new_build_id: str,
        data: AppUpdateData,
        now: datetime,
    ) -> None:
        # Compute depot diff using previous update's manifests
        size_bytes = 0
        prev_update = await self.update_repo.get_latest_for_game(game_id)
        prev_manifests = prev_update.manifest_changes if prev_update and prev_update.manifest_changes else None

        current_manifests = data.get_manifest_dict()
        depot_diff = data.compute_depot_diff(prev_manifests)
        depot_changes = {"changed": depot_diff} if depot_diff else {}

        # Determine if it's critical algorithmically based on affected depots
        from app.utils.depot_filter import determine_criticality
        is_critical, _ = determine_criticality(depot_changes.get("changed"))

        update = Update(
            game_id=game_id,
            build_id=new_build_id,
            previous_build_id=old_build_id,
            size_bytes=size_bytes if size_bytes > 0 else None,
            manifest_changes=current_manifests,
            depot_changes=depot_changes,
            raw_data=data.model_dump(mode="json"),
            detected_at=now,
        )

        created_update = await self.update_repo.create(update)

        await self.update_repo.append_timeline_event(
            update_id=created_update.id,
            event_type="build_detected",
            source=data.source,
            metadata={"build_id": new_build_id, "previous_build_id": old_build_id}
        )

        if size_bytes > 0:
            await self.update_repo.append_timeline_event(
                update_id=created_update.id,
                event_type="patch_size_detected",
                source=data.source,
                metadata={"size_bytes": size_bytes}
            )

        await logger.ainfo(
            "update_detected",
            game_id=str(game_id),
            new_build_id=new_build_id,
            old_build_id=old_build_id,
            size_bytes=size_bytes,
        )

        event = UpdateDetectedEvent(
            update_id=created_update.id,
            game_id=game_id,
            build_id=new_build_id,
            previous_build_id=old_build_id,
            is_critical=is_critical,
            detected_at=now,
            raw_data=data,
            depot_changes=depot_changes.get("changed") if depot_changes else None,
        )
        await self.event_bus.publish(event)
