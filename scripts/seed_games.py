"""
CS2 Instant Alert — Seed Initial Game Data.

Run this script to populate the database with the initial
Counter-Strike 2 game entry and its monitoring state.

Usage:
    python -m scripts.seed_games
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.database.session import DatabaseSessionManager
from app.models.game import Game
from app.models.steam_app_state import SteamAppState
from app.repositories.game_repository import GameRepository
from app.repositories.steam_state_repository import SteamStateRepository

logger = get_logger("system")

# ─── Game Definitions ───

GAMES = [
    {
        "steam_app_id": 730,
        "name": "Counter-Strike 2",
        "slug": "cs2",
        "icon_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/730/header.jpg",
        "monitor_config": {
            "branches": ["public"],
            "patch_notes_url": "https://www.counter-strike.net/news/updates",
            "news_feed_app_id": 730,
            "tracked_depots": [731, 2347771],
        },
    },
]


async def seed() -> None:
    """Seed the database with initial game data."""
    settings = get_settings()
    setup_logging(log_level=settings.app_log_level)

    db = DatabaseSessionManager(settings)
    await db.initialize()

    try:
        async with db.session() as session:
            game_repo = GameRepository(session)
            state_repo = SteamStateRepository(session)

            for game_data in GAMES:
                existing = await game_repo.get_by_steam_app_id(game_data["steam_app_id"])
                if existing:
                    print(f"  ⏭  Game '{game_data['name']}' already exists, skipping.")
                    continue

                game = Game(**game_data)
                created_game = await game_repo.create(game)

                # Create initial monitoring state
                state = SteamAppState(game_id=created_game.id)
                await state_repo.create(state)

                print(f"  ✅ Created game '{created_game.name}' (app_id={created_game.steam_app_id})")

        print("\n✅ Seed completed successfully.")
    finally:
        await db.close()


if __name__ == "__main__":
    print("🌱 Seeding game data...\n")
    asyncio.run(seed())
