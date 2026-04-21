from datetime import datetime, timezone
from typing import Any, cast

from arq import cron

from src.core.settings import settings
from src.models.monitor import Monitor
from src.worker.lifecycle import (
    WorkerContext,
    logger,
    shutdown,
    startup_scheduler,
)

# Queue name constants for cross-worker job routing
MONITORING_QUEUE = "arq:monitoring"

# =============================================================================
# CRON JOB: Scheduler
# =============================================================================


async def scheduler(ctx: dict[str, Any]) -> None:
    """Scheduler that processes due monitors and enqueues check tasks."""
    typed_ctx = cast(WorkerContext, ctx)
    redis = typed_ctx["redis"]
    session_factory = typed_ctx["session_factory"]

    logger.debug("scheduler_started", timestamp=datetime.now(timezone.utc).isoformat())

    now_ts = datetime.now(timezone.utc).timestamp()

    # Check total backlog BEFORE limiting to 100 (backlog monitoring)
    total_due = await redis.zcount("scheduler", "-inf", now_ts)

    if total_due > 100:
        logger.warning(
            "scheduler_backlog_high",
            total_due=total_due,
            processing_limit=100,
            backlog=total_due - 100,
        )

    due_monitors_raw = (
        await redis.zrangebyscore(  # pyright: ignore[reportUnknownMemberType]
            "scheduler",
            min="-inf",
            max=now_ts,
            start=0,
            num=100,
            score_cast_func=str,
        )
    )
    due_monitors = cast(list[str], due_monitors_raw)

    if not due_monitors:
        logger.debug("scheduler_idle")
        return

    logger.info("scheduler_processing", count=len(due_monitors))

    for monitor_id_raw in due_monitors:
        monitor_id = int(monitor_id_raw)

        # Enqueue check_monitor to the MONITORING worker queue
        await redis.enqueue_job(
            "check_monitor", monitor_id, _queue_name=MONITORING_QUEUE
        )

        interval_key = f"monitor:{monitor_id}:interval"
        interval_raw = await redis.get(interval_key)

        if interval_raw:
            interval = int(interval_raw)
            next_run = now_ts + interval
            await redis.zadd("scheduler", {str(monitor_id): next_run})
        else:
            # Fallback to DB - wrap in try-except to prevent one monitor's DB error
            # from killing the entire scheduler loop
            try:
                async with session_factory() as session:
                    monitor = await session.get(Monitor, monitor_id)
                    if not monitor:
                        logger.warning(
                            "scheduler_zombie_task_removed", monitor_id=monitor_id
                        )
                        await redis.zrem("scheduler", str(monitor_id))
                        await redis.delete(interval_key)
                        continue

                    if not monitor.is_active:
                        logger.info(
                            "scheduler_paused_task_removed", monitor_id=monitor_id
                        )
                        await redis.zrem("scheduler", str(monitor_id))
                        continue

                    await redis.set(interval_key, monitor.interval)

                    next_run = now_ts + monitor.interval
                    await redis.zadd("scheduler", {str(monitor_id): next_run})
            except Exception as e:
                logger.error(
                    "scheduler_db_error",
                    monitor_id=monitor_id,
                    error=str(e),
                    action="skipping_monitor",
                )
                continue

    logger.debug("scheduler_completed", queued_count=len(due_monitors))


class SchedulerWorkerSettings:
    """
    Scheduler Worker configuration for ARQ.

    This worker handles:
    - Cron-based scheduling of monitor checks every 15 seconds
    - Hydrating Redis cache on startup
    - Enqueuing check_monitor jobs to the monitoring worker queue
    """

    queue_name = "arq:scheduler"
    redis_settings = settings.redis.arq_settings

    functions = [scheduler]

    cron_jobs = [
        cron(
            scheduler,
            second={0, 15, 30, 45},  # Every 15 seconds for better UX
            unique=True,  # Prevent overlapping scheduler runs
        )
    ]

    on_startup = startup_scheduler
    on_shutdown = shutdown

    max_jobs = 10
    job_timeout = 30
