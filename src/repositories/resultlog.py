from datetime import datetime
from typing import List, Tuple

from sqlalchemy import select, func
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
        limit: int | None = None,
        offset: int | None = None,
    ) -> Tuple[List[ResultLog], int]:
        base_filter = (
            ResultLog.monitor_id == monitor_id,
            ResultLog.start_time >= start_time,
            ResultLog.start_time <= end_time,
        )

        count_query = select(func.count()).select_from(ResultLog).where(*base_filter)
        count_result = await self.session.execute(count_query)
        total_count = count_result.scalar() or 0

        query = (
            select(ResultLog).where(*base_filter).order_by(ResultLog.start_time.desc())
        )

        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)

        result = await self.session.execute(query)
        logs = list(result.scalars().all())

        return logs, total_count

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
