import asyncio
from typing import List, Tuple

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitor import Monitor
from src.schemas.monitor import MonitorCreate
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

    async def bulk_create_monitors(
        self, 
        monitors_data: List[MonitorCreate], 
        user_id: int
    ) -> List[Monitor]:
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