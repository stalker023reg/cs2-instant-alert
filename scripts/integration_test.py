"""
CS2 Instant Alert — Integration Test Script.
"""

import asyncio
import sys
from datetime import datetime, UTC
import uuid

from app.core.config import AppSettings
from app.database.session import DatabaseSessionManager
from app.core.container import Container
from app.events.types import UpdateDetectedEvent


async def test_integration():
    print("Starting Integration Test...")
    settings = AppSettings()
    
    print("1. Connecting to PostgreSQL...")
    db_manager = DatabaseSessionManager(settings.database_url)
    
    container = Container(config=settings, db_manager=db_manager)
    
    print("2. Initializing Steam Client (checks Redis implicitly)...")
    await container.steam_client().initialize()
    
    print("3. Starting EventBus & Core Services...")
    container.event_bus().start()
    
    # Subscribe PatchNotesService for testing
    container.event_bus().subscribe(
        UpdateDetectedEvent,
        container.patch_notes_service().start_polling_for_update
    )
    
    await container.notification_manager().start()
    await container.retry_engine().start()
    
    print("4. Testing Database Operations (User & Update Creation)...")
    async with db_manager.session() as session:
        from app.repositories.user_repository import UserRepository
        from app.repositories.subscription_repository import SubscriptionRepository
        from app.repositories.game_repository import GameRepository
        
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)
        game_repo = GameRepository(session)
        
        # Ensure CS2 exists
        game = await game_repo.get_by_steam_app_id(730)
        if not game:
            from app.models.game import Game
            game = Game(id=uuid.UUID("00000000-0000-0000-0000-000000000730"), steam_app_id=730, name="Counter-Strike 2", slug="cs2")
            session.add(game)
            await session.commit()
            await session.refresh(game)
            
        # Create dummy admin user for tests
        user = await user_repo.get_by_telegram_id(999999999)
        if not user:
            from app.models.user import User, UserSettings
            user = User(telegram_id=999999999, is_admin=True)
            user.settings = UserSettings(user_id=user.id)
            session.add(user)
            await session.commit()
            
            from app.models.subscription import Subscription
            sub = Subscription(user_id=user.id, game_id=game.id)
            session.add(sub)
            await session.commit()
            
    print("5. Emulating UpdateDetectedEvent...")
    event = UpdateDetectedEvent(
        update_id=uuid.uuid4(),
        game_id=game.id,
        game_slug="cs2",
        build_id="TEST_BUILD_" + str(int(datetime.now().timestamp())),
        detected_at=datetime.now(UTC),
        is_race_mode=True
    )
    
    await container.event_bus().publish(event)
    
    print("Waiting for processing (3 seconds)...")
    await asyncio.sleep(3)
    
    print("6. Verifying NotificationHistory...")
    async with db_manager.session() as session:
        from sqlalchemy import select
        from app.models.notification_history import NotificationHistory
        stmt = select(NotificationHistory).where(NotificationHistory.update_id == event.update_id)
        histories = (await session.scalars(stmt)).all()
        print(f"   Found {len(histories)} notification records for this update.")
        
    print("Integration Test Complete. Shutting down...")
    await container.retry_engine().stop()
    await container.notification_manager().stop()
    container.event_bus().stop()
    await container.steam_client().close()
    await db_manager.close()
    
if __name__ == "__main__":
    asyncio.run(test_integration())
