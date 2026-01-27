import asyncio
from typing import List, Tuple

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitor import Monitor
from src.schemas.monitor import MonitorCreate, MonitoringStatus
from src.worker.main import get_next_aligned_time


class MonitorService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _check_single_url(
        self, 
        client: httpx.AsyncClient, 
        url: str
    ) -> Tuple[str, bool, str | None]:
        try:
            response = await client.get(url, timeout=5.0)
            is_alive = True 
            error = None
            # 4xx and 5xx codes are errors, but the site is technically responding
            # For monitoring purposes, we consider this a “problem"
            if response.status_code >= 400:
                error = f"Status code: {response.status_code}"
        except httpx.RequestError as e:
            is_alive = False
            error = str(e)
        
        return url, is_alive, error

    async def get_all_by_user(self, user_id: int) -> List[Monitor]:
        """Get all monitors for a specific user."""
        query = select(Monitor).where(Monitor.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, monitor_id: int, user_id: int) -> Monitor | None:
        """Get a specific monitor by ID for a user."""
        query = select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.user_id == user_id
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def bulk_create_monitors(
        self, 
        monitors_data: List[MonitorCreate], 
        user_id: int
    ) -> List[Monitor]:
        """Create multiple monitors with initial URL validation."""
        # One client for all requests
        async with httpx.AsyncClient() as client:
            tasks = []
            for data in monitors_data:
                # Preparing coroutines for parallel execution
                tasks.append(self._check_single_url(client, str(data.url)))
            
            # gather() runs all coroutines “simultaneously”
            # Returns results in the same order
            results = await asyncio.gather(*tasks)

        new_monitors = []
        
        for data, (url, is_alive, error) in zip(monitors_data, results):
            if not is_alive:
                print(f"⚠️ Warning: Сайт {url} недоступен при добавлении! Ошибка: {error}")
            else:
                print(f"✅ Success: Сайт {url} успешно проверен.")

            next_aligned_time = get_next_aligned_time(data.interval)
            
            monitor = Monitor(
                user_id=user_id,
                url=str(data.url),
                name=data.name or str(data.url),
                interval=data.interval,
                method=data.method,
                is_active=True,
                next_check_at=next_aligned_time,
                last_check_status=None,
            )
            new_monitors.append(monitor)

        self.session.add_all(new_monitors)
        await self.session.commit()
        
        # refresh() is needed to obtain the generated fields (id)
        for m in new_monitors:
            await self.session.refresh(m)
            
        return new_monitors

    async def start_all(self, user_id: int, username: str) -> MonitoringStatus:
        """Activate all monitors for a user."""
        query = (
            update(Monitor)
            .where(Monitor.user_id == user_id)
            .values(is_active=True)
        )
        result = await self.session.execute(query)
        await self.session.commit()
        
        print(f"▶️ User {username} started monitoring ({result.rowcount} monitors)")
        
        return MonitoringStatus(
            status="started",
            message=f"Activated {result.rowcount} monitor(s)",
            affected_count=result.rowcount
        )

    async def stop_all(self, user_id: int, username: str) -> MonitoringStatus:
        """Deactivate all monitors for a user."""
        query = (
            update(Monitor)
            .where(Monitor.user_id == user_id)
            .values(is_active=False)
        )
        result = await self.session.execute(query)
        await self.session.commit()
        
        print(f"⏹️ User {username} stopped monitoring ({result.rowcount} monitors)")
        
        return MonitoringStatus(
            status="stopped",
            message=f"Deactivated {result.rowcount} monitor(s)",
            affected_count=result.rowcount
        )

    async def toggle(self, monitor: Monitor) -> Monitor:
        """Toggle monitor active state."""
        monitor.is_active = not monitor.is_active
        await self.session.commit()
        await self.session.refresh(monitor)
        
        state = "activated" if monitor.is_active else "deactivated"
        print(f"🔄 Monitor {monitor.id} ({monitor.url}) {state}")
        
        return monitor

    async def delete(self, monitor: Monitor) -> None:
        """Delete a monitor."""
        print(f"🗑️ Monitor {monitor.id} ({monitor.url}) deleted")
        await self.session.delete(monitor)
        await self.session.commit()