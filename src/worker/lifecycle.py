from typing import Any
import json

import httpx
from sqlalchemy import select, func

from src.config.settings import settings
from src.core.database import async_session_factory
from src.core.logging import configure_logging, get_logger
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog
from src.models.user import User
from src.telegram.notifier import TelegramNotifier
from src.utils.time import get_next_aligned_time

configure_logging(
    service="worker",
    json_logs=not settings.debug_mode,
    log_level="DEBUG" if settings.debug_mode else "INFO",
    enable_file_logging=settings.enable_file_logging,
)
logger = get_logger("worker")


async def hydrate_cache(ctx: dict[str, Any]):
    """Initialize Redis cache with active monitors and restore last known states from DB logs."""
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    logger.info("hydrate_cache_started")

    # Clear old scheduler data
    await redis.delete("scheduler")

    async with session_factory() as session:
        latest_log_subquery = (
            select(
                ResultLog.monitor_id,
                func.max(ResultLog.start_time).label("last_start_time"),
            )
            .group_by(ResultLog.monitor_id)
            .subquery()
        )

        query = (
            select(Monitor, User, ResultLog)
            .join(User, Monitor.user_id == User.id)
            .outerjoin(
                latest_log_subquery,
                Monitor.id == latest_log_subquery.c.monitor_id,
            )
            .outerjoin(
                ResultLog,
                (ResultLog.monitor_id == latest_log_subquery.c.monitor_id)
                & (ResultLog.start_time == latest_log_subquery.c.last_start_time),
            )
            .where(Monitor.is_active == True)  # noqa: E712
        )

        result = await session.execute(query)
        rows = result.all()

        if not rows:
            logger.info("hydrate_cache_no_monitors")
            return

        logger.info("hydrate_cache_loading", count=len(rows))

        async with redis.pipeline() as pipe:
            for monitor, user, last_log in rows:
                # Store interval
                pipe.set(f"monitor:{monitor.id}:interval", monitor.interval)

                # Store full config as JSON to avoid DB hits on every check
                config = {
                    "url": monitor.url,
                    "method": monitor.method,
                    "headers": monitor.headers or {},
                    "body": monitor.body,
                    "is_active": monitor.is_active,
                    "name": monitor.name,
                    "user_id": monitor.user_id,
                    "username": user.username,
                    "telegram_chat_id": user.telegram_chat_id,
                }

                pipe.setex(f"monitor:{monitor.id}:config", 86400, json.dumps(config))

                next_run = get_next_aligned_time(monitor.interval).timestamp()
                pipe.zadd("scheduler", {str(monitor.id): next_run})

                if last_log:
                    # Restore state from last check (TTL 24h to auto-cleanup)
                    # NOTE: We intentionally DO NOT restore last_check_time here
                    # to prevent false recovery alerts on first check after worker restart
                    state_key = f"monitor:{monitor.id}:state"
                    pipe.setex(state_key, 86400, "1" if last_log.is_success else "0")

                    logger.debug(
                        "state_restored",
                        monitor_id=monitor.id,
                        last_status=last_log.is_success,
                        last_check=last_log.start_time.isoformat(),
                    )

            await pipe.execute()

        logger.info("hydrate_cache_completed", monitors_loaded=len(rows))


async def startup_monitoring(ctx: dict[str, Any]) -> None:
    """Startup for monitoring worker - initializes HTTP client and hydrates cache."""
    logger.info(
        "monitoring_startup",
        database_host=settings.db.HOST,
        database_port=settings.db.PORT,
        redis_host=settings.redis.R_HOST,
        redis_port=settings.redis.R_PORT,
    )

    ctx["http_client"] = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=True,
    )

    ctx["session_factory"] = async_session_factory

    await hydrate_cache(ctx)

    logger.info("monitoring_worker_ready")


async def startup_alerting(ctx: dict[str, Any]) -> None:
    """Startup for alerting worker - initializes HTTP client and Telegram notifier."""
    logger.info(
        "alerting_startup",
        database_host=settings.db.HOST,
        database_port=settings.db.PORT,
        redis_host=settings.redis.R_HOST,
        redis_port=settings.redis.R_PORT,
        telegram_enabled=True,
    )

    ctx["http_client"] = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=True,
    )

    ctx["session_factory"] = async_session_factory
    ctx["notifier"] = TelegramNotifier(http_client=ctx["http_client"])

    logger.info("alerting_worker_ready")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("shutdown_started")

    http_client: httpx.AsyncClient = ctx.get("http_client")
    if http_client:
        await http_client.aclose()
        logger.info("http_client_closed")

    logger.info("shutdown_complete")
