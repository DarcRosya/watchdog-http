from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitor import Monitor


class MonitorRepository:
    """Repository for Monitor model - handles database operations only."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, monitor_id: int, user_id: int) -> Monitor | None:
        """Get a specific monitor by ID for a user."""
        query = select(Monitor).where(
            Monitor.id == monitor_id, Monitor.user_id == user_id
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_all_by_user(self, user_id: int) -> list[Monitor]:
        """Get all monitors for a specific user."""
        query = select(Monitor).where(Monitor.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_by_user(self, user_id: int) -> list[Monitor]:
        """Get all active monitors for a specific user."""
        query = select(Monitor).where(
            Monitor.user_id == user_id,
            Monitor.is_active.is_(True),
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_ids_by_user(self, user_id: int) -> list[int]:
        """Get IDs of all active monitors for a specific user."""
        query = select(Monitor.id).where(
            Monitor.user_id == user_id,
            Monitor.is_active.is_(True),
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, monitor: Monitor) -> Monitor:
        """Create a new monitor."""
        self.session.add(monitor)
        await self.session.commit()
        await self.session.refresh(monitor)
        return monitor

    async def bulk_create(self, monitors: list[Monitor]) -> list[Monitor]:
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
        result = cast(CursorResult[Any], await self.session.execute(query))
        await self.session.commit()
        return max(result.rowcount, 0)

    async def deactivate_all(self, user_id: int) -> int:
        """Deactivate all monitors for a user. Returns count of affected rows."""
        query = (
            update(Monitor).where(Monitor.user_id == user_id).values(is_active=False)
        )
        result = cast(CursorResult[Any], await self.session.execute(query))
        await self.session.commit()
        return max(result.rowcount, 0)

    async def delete(self, monitor: Monitor) -> None:
        """Delete a monitor."""
        await self.session.delete(monitor)
        await self.session.commit()
