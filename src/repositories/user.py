from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User


class UserRepository:
    """Repository for User model - handles database operations only."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by ID."""
        query = select(User).where(User.id == user_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_ids(self, user_ids: List[int]) -> dict[int, User]:
        """Get multiple users by IDs. Returns dict mapping user_id -> User."""
        query = select(User).where(User.id.in_(user_ids))
        result = await self.session.execute(query)
        return {user.id: user for user in result.scalars().all()}

    async def get_by_username(self, username: str) -> User | None:
        """Get user by username."""
        query = select(User).where(User.username == username)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_api_key(self, api_key: str) -> User | None:
        """Get user by API key."""
        query = select(User).where(User.api_key == api_key)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_telegram_id(self, telegram_chat_id: int) -> User | None:
        """Get user by Telegram chat ID."""
        query = select(User).where(User.telegram_chat_id == telegram_chat_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def create(self, user: User) -> User:
        """Create a new user."""
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_fields(self, user: User) -> User:
        """Update user fields (call after modifying user object)."""
        await self.session.commit()
        await self.session.refresh(user)
        return user
