from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self, 
        username: str, 
        telegram_chat_id: Optional[int] = None
    ) -> User:
        user = User(
            username=username,
            telegram_chat_id=telegram_chat_id
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        
        print(f"✅ User created: id={user.id}, username={user.username}")
        
        return user

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        query = select(User).where(User.id == user_id)
        result = await self.session.execute(query)

        return result.scalars().first()

    async def get_user_by_telegram_id(self, telegram_chat_id: int) -> Optional[User]:
        query = select(User).where(User.telegram_chat_id == telegram_chat_id)
        result = await self.session.execute(query)

        return result.scalars().first()

    async def get_or_create_user(
        self, 
        username: str, 
        telegram_chat_id: Optional[int] = None
    ) -> tuple[User, bool]:
        if telegram_chat_id:
            existing = await self.get_user_by_telegram_id(telegram_chat_id)
            if existing:
                print(f"ℹ️ User found by telegram_id: {existing.username}")
                return existing, False

        new_user = await self.create_user(username, telegram_chat_id)
        return new_user, True
