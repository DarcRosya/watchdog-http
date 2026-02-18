from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.resultlog import ResultLog


class ResultLogRepository:
    """Repository for ResultLog model - handles database operations only."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_monitor(
        self,
        monitor_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[ResultLog]:
        """Get all logs for a monitor within time range."""
        query = (
            select(ResultLog)
            .where(
                ResultLog.monitor_id == monitor_id,
                ResultLog.start_time >= start_time,
                ResultLog.start_time <= end_time,
            )
            .order_by(ResultLog.start_time.asc())
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_latest_by_monitor(self, monitor_id: int) -> ResultLog | None:
        """Get the most recent log entry for a monitor."""
        query = (
            select(ResultLog)
            .where(ResultLog.monitor_id == monitor_id)
            .order_by(ResultLog.start_time.desc())
            .limit(1)
        )

        result = await self.session.execute(query)
        return result.scalars().first()

    async def create(self, log: ResultLog) -> ResultLog:
        """Create a new log entry."""
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log
