from typing import Optional

from src.core.logging import get_logger
from src.models.user import User
from src.repositories.user import UserRepository
from src.schemas.user import UserUpdate
from src.telegram.bot import refresh_user_monitor_cache

logger = get_logger("service")


class UserService:
    """Service layer for User business logic."""

    def __init__(self, session):
        self.user_repo = UserRepository(session)

    async def create_user(self) -> User:
        """Create user with auto-generated username and API key."""
        from src.utils.random_generate import generate_random_username

        username = generate_random_username()
        user = User(username=username)
        user = await self.user_repo.create(user)

        logger.info("user_created", user_id=user.id, username=user.username)

        return user

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        return await self.user_repo.get_by_id(user_id)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        return await self.user_repo.get_by_username(username)

    async def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        """Get user by API key."""
        return await self.user_repo.get_by_api_key(api_key)

    async def get_user_by_telegram_id(self, telegram_chat_id: int) -> Optional[User]:
        """Get user by Telegram chat ID."""
        return await self.user_repo.get_by_telegram_id(telegram_chat_id)

    async def update_user(self, user_id: int, update_data: UserUpdate) -> User:
        """Update user profile."""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User with id={user_id} not found")

        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(user, field, value)

        updated_user = await self.user_repo.update_fields(user)

        logger.info(
            "user_updated",
            user_id=user_id,
            updated_fields=list(update_dict.keys()),
        )

        return updated_user
