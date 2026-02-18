from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitor import Monitor


class MonitorRepository:
    """Repository for Monitor model - handles database operations only."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, monitor_id: int, user_id: int) -> Monitor | None:
        """Get a specific monitor by ID for a user."""
        query = select(Monitor).where(
            Monitor.id == monitor_id, Monitor.user_id == user_id
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_all_by_user(self, user_id: int) -> List[Monitor]:
        """Get all monitors for a specific user."""
        query = select(Monitor).where(Monitor.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_by_user(self, user_id: int) -> List[Monitor]:
        """Get all active monitors for a specific user."""
        query = select(Monitor).where(
            Monitor.user_id == user_id, Monitor.is_active == True  # noqa: E712
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_ids_by_user(self, user_id: int) -> List[int]:
        """Get IDs of all active monitors for a specific user."""
        query = select(Monitor.id).where(
            Monitor.user_id == user_id, Monitor.is_active == True  # noqa: E712
        )
        result = await self.session.execute(query)
        return [row[0] for row in result.all()]

    async def create(self, monitor: Monitor) -> Monitor:
        """Create a new monitor."""
        self.session.add(monitor)
        await self.session.commit()
        await self.session.refresh(monitor)
        return monitor

    async def bulk_create(self, monitors: List[Monitor]) -> List[Monitor]:
        """Create multiple monitors at once."""
        self.session.add_all(monitors)
        await self.session.commit()

        for monitor in monitors:
            await self.session.refresh(monitor)

        return monitors

    async def update_fields(self, monitor: Monitor) -> Monitor:
        """Update monitor fields (call after modifying monitor object)."""
        await self.session.commit()
        await self.session.refresh(monitor)
        return monitor

    async def activate_all(self, user_id: int) -> int:
        """Activate all monitors for a user. Returns count of affected rows."""
        query = update(Monitor).where(Monitor.user_id == user_id).values(is_active=True)
        result = await self.session.execute(query)
        await self.session.commit()
        return result.rowcount

    async def deactivate_all(self, user_id: int) -> int:
        """Deactivate all monitors for a user. Returns count of affected rows."""
        query = (
            update(Monitor).where(Monitor.user_id == user_id).values(is_active=False)
        )
        result = await self.session.execute(query)
        await self.session.commit()
        return result.rowcount

    async def delete(self, monitor: Monitor) -> None:
        """Delete a monitor."""
        await self.session.delete(monitor)
        await self.session.commit()
