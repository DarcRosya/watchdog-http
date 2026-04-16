from datetime import datetime, timedelta
from typing import Any, Callable, List, Literal, cast

import httpx  # type: ignore # noqa: F401 - imported for tests that monkeypatch src.services.monitor httpx
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

import src.core.logging as app_logging
from src.models.monitor import Monitor
from src.repositories.monitor import MonitorRepository
from src.repositories.resultlog import ResultLogRepository
from src.repositories.user import UserRepository
from src.schemas.monitor import MonitorCreate, MonitoringStatus, MonitorUpdate
from src.utils.time import get_next_aligned_time

GetLogger = Callable[[Literal["api", "worker", "telegram", "service"]], Any]
get_logger = cast(GetLogger, app_logging.get_logger)
logger = get_logger("service")


class MonitorService:
    """Service layer for Monitor business logic and Redis operations."""

    def __init__(
        self, session: AsyncSession, redis: aioredis.Redis | None = None
    ) -> None:
        self.redis = redis
        self.monitor_repo = MonitorRepository(session)
        self.user_repo = UserRepository(session)
        self.resultlog_repo = ResultLogRepository(session)

    async def get_all_by_user(self, user_id: int) -> List[Monitor]:
        """Get all monitors for a specific user."""
        return await self.monitor_repo.get_all_by_user(user_id)

    async def get_by_id(self, monitor_id: int, user_id: int) -> Monitor | None:
        """Get a specific monitor by ID for a user."""
        return await self.monitor_repo.get_by_id(monitor_id, user_id)

    async def bulk_create_monitors(
        self, monitors_data: List[MonitorCreate], user_id: int
    ) -> List[Monitor]:
        """Create multiple monitors with initial URL validation."""
        new_monitors: List[Monitor] = []

        for data in monitors_data:
            monitor = Monitor(
                user_id=user_id,
                url=str(data.url),
                name=data.name or str(data.url),
                interval=data.interval,
                method=data.method,
                headers=data.headers or None,
                body=data.body or None,
                is_active=True,
            )
            new_monitors.append(monitor)

        new_monitors = await self.monitor_repo.bulk_create(new_monitors)

        if self.redis:
            await self._add_monitors_to_redis(new_monitors)

        return new_monitors

    async def _add_monitors_to_redis(self, monitors: List[Monitor]) -> None:
        """Add monitors to Redis scheduler (used after creation or activation)."""
        if not self.redis:
            return

        import json

        # Fetch user data for all monitors
        user_ids = list(set(m.user_id for m in monitors))
        users = await self.user_repo.get_by_ids(user_ids)

        async with self.redis.pipeline() as pipe:
            for monitor in monitors:
                if monitor.is_active:
                    user = users.get(monitor.user_id)

                    pipe.set(f"monitor:{monitor.id}:interval", monitor.interval)

                    config: dict[str, Any] = {
                        "url": monitor.url,
                        "method": monitor.method,
                        "headers": monitor.headers or {},
                        "body": monitor.body,
                        "is_active": monitor.is_active,
                        "name": monitor.name,
                        "user_id": monitor.user_id,
                        "username": user.username if user else "unknown",
                        "telegram_chat_id": user.telegram_chat_id if user else None,
                    }
                    pipe.setex(
                        f"monitor:{monitor.id}:config", 86400, json.dumps(config)
                    )

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
                pipe.zrem("scheduler", str(monitor_id))

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

        # Fetch user data
        user = await self.user_repo.get_by_id(monitor.user_id)

        config: dict[str, Any] = {
            "url": monitor.url,
            "method": monitor.method,
            "headers": monitor.headers or {},
            "body": monitor.body,
            "is_active": monitor.is_active,
            "name": monitor.name,
            "user_id": monitor.user_id,
            "username": user.username if user else "unknown",
            "telegram_chat_id": user.telegram_chat_id if user else None,
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
        affected_count = await self.monitor_repo.activate_all(user_id)

        if self.redis and affected_count > 0:
            monitors = await self.monitor_repo.get_active_by_user(user_id)
            await self._add_monitors_to_redis(monitors)

        logger.info(
            "monitoring_started",
            user=username,
            user_id=user_id,
            affected_count=affected_count,
        )

        return MonitoringStatus(
            status="started",
            message=f"Activated {affected_count} monitor(s)",
            affected_count=affected_count,
        )

    async def stop_all(self, user_id: int, username: str) -> MonitoringStatus:
        """Deactivate all monitors for a user."""
        monitor_ids = []
        if self.redis:
            monitor_ids = await self.monitor_repo.get_active_ids_by_user(user_id)

        affected_count = await self.monitor_repo.deactivate_all(user_id)

        if self.redis and monitor_ids:
            await self._remove_monitors_from_redis(monitor_ids)

        logger.info(
            "monitoring_stopped",
            user=username,
            user_id=user_id,
            affected_count=affected_count,
        )

        return MonitoringStatus(
            status="stopped",
            message=f"Deactivated {affected_count} monitor(s)",
            affected_count=affected_count,
        )

    async def toggle(self, monitor: Monitor) -> Monitor:
        """Toggle monitor active state."""
        monitor.is_active = not monitor.is_active
        monitor = await self.monitor_repo.update_fields(monitor)

        if self.redis:
            if monitor.is_active:
                await self._add_monitors_to_redis([monitor])
            else:
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

        if self.redis:
            await self._remove_monitors_from_redis([monitor_id])

        logger.info("monitor_deleted", monitor_id=monitor_id, url=monitor_url)
        await self.monitor_repo.delete(monitor)

    async def update(self, monitor: Monitor, update_data: MonitorUpdate) -> Monitor:
        """Update monitor configuration."""
        update_dict = update_data.model_dump(exclude_unset=True)

        if "url" in update_dict and update_dict["url"] is not None:
            update_dict["url"] = str(update_dict["url"])

        if "method" in update_dict and update_dict["method"] is not None:
            update_dict["method"] = update_dict["method"].value

        for field, value in update_dict.items():
            setattr(monitor, field, value)

        monitor = await self.monitor_repo.update_fields(monitor)

        if self.redis:
            await self._update_monitor_config_in_redis(monitor)

        logger.info(
            "monitor_updated",
            monitor_id=monitor.id,
            url=monitor.url,
            updated_fields=list(update_dict.keys()),
        )

        return monitor

    async def get_statistics(
        self,
        monitor_id: int,
        user_id: int,
        hours: int = 24,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        monitor = await self.monitor_repo.get_by_id(monitor_id, user_id)
        if not monitor:
            return {"data": [], "total": 0, "limit": limit, "offset": offset or 0}

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

        # Use repository to fetch logs with pagination
        logs, total_count = await self.resultlog_repo.get_by_monitor(
            monitor_id, start_time, end_time, limit, offset
        )

        data: list[dict[str, Any]] = [
            {
                "start_time": log.start_time.isoformat(),
                "duration_ms": log.duration_ms,
                "status_code": log.status_code,
                "is_success": log.is_success,
                "error_message": log.error_message,
            }
            for log in logs
        ]

        return {
            "data": data,
            "total": total_count,
            "limit": limit,
            "offset": offset or 0,
        }
