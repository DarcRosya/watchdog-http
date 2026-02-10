import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog
from src.schemas.monitor import MonitorCreate, MonitoringStatus
from src.worker.main import get_next_aligned_time

logger = get_logger("service")


class MonitorService:
    def __init__(self, session: AsyncSession, redis: aioredis.Redis | None = None):
        self.session = session
        self.redis = redis

    async def _check_single_url(
        self, client: httpx.AsyncClient, url: str
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
            Monitor.id == monitor_id, Monitor.user_id == user_id
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def bulk_create_monitors(
        self, monitors_data: List[MonitorCreate], user_id: int
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
                logger.warning("monitor_url_unavailable", url=url, error=error)
            else:
                logger.info("monitor_url_checked", url=url, is_alive=True)

            monitor = Monitor(
                user_id=user_id,
                url=str(data.url),
                name=data.name or str(data.url),
                interval=data.interval,
                method=data.method,
                is_active=True,
            )
            new_monitors.append(monitor)

        self.session.add_all(new_monitors)
        await self.session.commit()

        # refresh() is needed to obtain the generated fields (id)
        for m in new_monitors:
            await self.session.refresh(m)

        # Add monitors to Redis scheduler
        if self.redis:
            await self._add_monitors_to_redis(new_monitors)

        return new_monitors

    async def _add_monitors_to_redis(self, monitors: List[Monitor]) -> None:
        """Add monitors to Redis scheduler (used after creation or activation)."""
        if not self.redis:
            return

        import json

        async with self.redis.pipeline() as pipe:
            for monitor in monitors:
                if monitor.is_active:
                    # Store interval
                    pipe.set(f"monitor:{monitor.id}:interval", monitor.interval)

                    # Store full config as JSON (avoid DB hits in check_monitor)
                    config = {
                        "url": monitor.url,
                        "method": monitor.method,
                        "headers": monitor.headers or {},
                        "body": monitor.body,
                        "is_active": monitor.is_active,
                        "name": monitor.name,
                        "user_id": monitor.user_id,
                    }
                    pipe.setex(
                        f"monitor:{monitor.id}:config", 86400, json.dumps(config)
                    )

                    # Schedule next check
                    next_run = get_next_aligned_time(monitor.interval).timestamp()
                    pipe.zadd("scheduler", {str(monitor.id): next_run})

                    logger.debug(
                        "monitor_added_to_redis",
                        monitor_id=monitor.id,
                        url=monitor.url,
                        next_run=next_run,
                    )

            await pipe.execute()

    async def _remove_monitors_from_redis(self, monitor_ids: List[int]) -> None:
        """Remove monitors from Redis scheduler (used after deletion or deactivation)."""
        if not self.redis:
            return

        async with self.redis.pipeline() as pipe:
            for monitor_id in monitor_ids:
                # Remove from scheduler
                pipe.zrem("scheduler", str(monitor_id))

                # Clean up monitor data
                pipe.delete(f"monitor:{monitor_id}:interval")
                pipe.delete(f"monitor:{monitor_id}:config")
                pipe.delete(f"monitor:{monitor_id}:state")
                pipe.delete(f"monitor:{monitor_id}:failures")
                pipe.delete(f"monitor:{monitor_id}:last_check_time")

                logger.debug("monitor_removed_from_redis", monitor_id=monitor_id)

            await pipe.execute()

    async def _update_monitor_config_in_redis(self, monitor: Monitor) -> None:
        """Update monitor config in Redis (used when monitor settings change)."""
        if not self.redis:
            return

        import json

        config = {
            "url": monitor.url,
            "method": monitor.method,
            "headers": monitor.headers or {},
            "body": monitor.body,
            "is_active": monitor.is_active,
            "name": monitor.name,
            "user_id": monitor.user_id,
        }

        async with self.redis.pipeline() as pipe:
            pipe.setex(f"monitor:{monitor.id}:config", 86400, json.dumps(config))
            pipe.set(f"monitor:{monitor.id}:interval", monitor.interval)

            # Update next run time if interval changed
            if monitor.is_active:
                next_run = get_next_aligned_time(monitor.interval).timestamp()
                pipe.zadd("scheduler", {str(monitor.id): next_run})

            await pipe.execute()

        logger.debug("monitor_config_updated_in_redis", monitor_id=monitor.id)

    async def start_all(self, user_id: int, username: str) -> MonitoringStatus:
        """Activate all monitors for a user."""
        query = update(Monitor).where(Monitor.user_id == user_id).values(is_active=True)
        result = await self.session.execute(query)
        await self.session.commit()

        # Get activated monitors to add to Redis
        if self.redis and result.rowcount > 0:
            monitors_query = select(Monitor).where(
                Monitor.user_id == user_id, Monitor.is_active == True  # noqa: E712
            )
            monitors_result = await self.session.execute(monitors_query)
            monitors = monitors_result.scalars().all()
            await self._add_monitors_to_redis(list(monitors))

        logger.info(
            "monitoring_started",
            user=username,
            user_id=user_id,
            affected_count=result.rowcount,
        )

        return MonitoringStatus(
            status="started",
            message=f"Activated {result.rowcount} monitor(s)",
            affected_count=result.rowcount,
        )

    async def stop_all(self, user_id: int, username: str) -> MonitoringStatus:
        """Deactivate all monitors for a user."""
        # Get monitor IDs before deactivating
        if self.redis:
            monitors_query = select(Monitor.id).where(
                Monitor.user_id == user_id, Monitor.is_active == True  # noqa: E712
            )
            monitors_result = await self.session.execute(monitors_query)
            monitor_ids = [row[0] for row in monitors_result.all()]

        query = (
            update(Monitor).where(Monitor.user_id == user_id).values(is_active=False)
        )
        result = await self.session.execute(query)
        await self.session.commit()

        # Remove from Redis scheduler
        if self.redis and monitor_ids:
            await self._remove_monitors_from_redis(monitor_ids)

        logger.info(
            "monitoring_stopped",
            user=username,
            user_id=user_id,
            affected_count=result.rowcount,
        )

        return MonitoringStatus(
            status="stopped",
            message=f"Deactivated {result.rowcount} monitor(s)",
            affected_count=result.rowcount,
        )

    async def toggle(self, monitor: Monitor) -> Monitor:
        """Toggle monitor active state."""
        monitor.is_active = not monitor.is_active
        await self.session.commit()
        await self.session.refresh(monitor)

        # Update Redis scheduler
        if self.redis:
            if monitor.is_active:
                # Activated - add to scheduler
                await self._add_monitors_to_redis([monitor])
            else:
                # Deactivated - remove from scheduler
                await self._remove_monitors_from_redis([monitor.id])

        state = "activated" if monitor.is_active else "deactivated"
        logger.info(
            "monitor_toggled", monitor_id=monitor.id, url=monitor.url, state=state
        )

        return monitor

    async def delete(self, monitor: Monitor) -> None:
        """Delete a monitor."""
        monitor_id = monitor.id
        monitor_url = monitor.url

        # Remove from Redis first
        if self.redis:
            await self._remove_monitors_from_redis([monitor_id])

        logger.info("monitor_deleted", monitor_id=monitor_id, url=monitor_url)
        await self.session.delete(monitor)
        await self.session.commit()

    async def get_statistics(
        self, monitor_id: int, user_id: int, hours: int = 24
    ) -> List[dict]:
        monitor = await self.get_by_id(monitor_id, user_id)
        if not monitor:
            return []

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

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
        logs = result.scalars().all()

        return [
            {
                "start_time": log.start_time.isoformat(),
                "duration_ms": log.duration_ms,
                "status_code": log.status_code,
                "is_success": log.is_success,
                "error_message": log.error_message,
            }
            for log in logs
        ]
