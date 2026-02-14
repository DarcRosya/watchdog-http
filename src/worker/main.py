from datetime import datetime, timedelta, timezone
from typing import Any
import json

import httpx
from arq import cron
from sqlalchemy import select, func

from src.config.settings import settings
from src.core.database import async_session_factory
from src.core.logging import configure_logging, get_logger
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog
from src.models.user import User
from src.telegram.notifier import (
    TelegramNotifier,
    AlertType,
    get_predefined_message,
)

configure_logging(
    service="worker",
    json_logs=not settings.debug_mode,
    log_level="DEBUG" if settings.debug_mode else "INFO",
    enable_file_logging=settings.enable_file_logging,
)
logger = get_logger("worker")


def get_next_aligned_time(interval_seconds: int = 60) -> datetime:
    now = datetime.now(timezone.utc)
    aligned_now = now.replace(second=0, microsecond=0)

    return aligned_now + timedelta(seconds=interval_seconds)


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


async def startup(ctx: dict[str, Any]) -> None:
    logger.info(
        "startup",
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

    # reuses http_client
    ctx["notifier"] = TelegramNotifier(http_client=ctx["http_client"])

    await hydrate_cache(ctx)

    logger.info("worker_ready")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("shutdown_started")

    http_client: httpx.AsyncClient = ctx.get("http_client")
    if http_client:
        await http_client.aclose()
        logger.info("http_client_closed")

    logger.info("shutdown_complete")


# =============================================================================
# TASK: Send HTTP error alert (based on logs)
# =============================================================================


async def send_alert_http_error(ctx: dict[str, Any], monitor_id: int) -> dict[str, Any]:
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    notifier: TelegramNotifier = ctx["notifier"]

    config_key = f"monitor:{monitor_id}:config"
    config_raw = await redis.get(config_key)

    if not config_raw:
        logger.warning("http_alert_monitor_not_found", monitor_id=monitor_id)
        return {"status": "skipped", "reason": "not_found"}

    config = json.loads(config_raw)

    if not config["telegram_chat_id"]:
        logger.info(
            "http_alert_skipped_no_telegram",
            user=config["username"],
            monitor_id=monitor_id,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    # Need to fetch last log from DB for status_code and duration_ms
    async with session_factory() as session:
        log_query = (
            select(ResultLog)
            .where(ResultLog.monitor_id == monitor_id)
            .order_by(ResultLog.start_time.desc())
            .limit(1)
        )
        log_result = await session.execute(log_query)
        last_log = log_result.scalars().first()

    message = get_predefined_message(
        alert_type=AlertType.HTTP_ERROR,
        monitor_name=config["name"] or "",
        url=config["url"],
        status_code=last_log.status_code if last_log else None,
        duration_ms=last_log.duration_ms if last_log else None,
    )

    success = await notifier.send_alert(config["telegram_chat_id"], message)

    if success:
        logger.info(
            "alert_sent",
            alert_type="http_error",
            user=config["username"],
            monitor_id=monitor_id,
            monitor_name=config["name"],
            url=config["url"],
        )
    else:
        logger.error(
            "alert_failed",
            alert_type="http_error",
            user=config["username"],
            monitor_id=monitor_id,
        )

    return {
        "status": "sent" if success else "failed",
        "monitor_id": monitor_id,
        "user": config["username"],
    }


# =============================================================================
# TASK: Send exception-based alert (no logs needed)
# =============================================================================


async def send_alert_exception(
    ctx: dict[str, Any],
    monitor_id: int,
    alert_type: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    redis = ctx["redis"]
    notifier: TelegramNotifier = ctx["notifier"]

    alert_type_map = {
        "timeout": AlertType.TIMEOUT,
        "connection": AlertType.CONNECTION_ERROR,
        "request": AlertType.REQUEST_ERROR,
    }
    alert_enum = alert_type_map.get(alert_type, AlertType.REQUEST_ERROR)

    config_key = f"monitor:{monitor_id}:config"
    config_raw = await redis.get(config_key)

    if not config_raw:
        logger.warning(
            "alert_monitor_not_found", monitor_id=monitor_id, alert_type=alert_type
        )
        return {"status": "skipped", "reason": "not_found"}

    config = json.loads(config_raw)

    if not config["telegram_chat_id"]:
        logger.info(
            "alert_skipped_no_telegram",
            user=config["username"],
            monitor_id=monitor_id,
            alert_type=alert_type,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    message = get_predefined_message(
        alert_type=alert_enum,
        monitor_name=config["name"] or "",
        url=config["url"],
        error=error_message,
    )

    success = await notifier.send_message(config["telegram_chat_id"], message)

    if success:
        logger.info(
            "alert_sent",
            alert_type=alert_type,
            user=config["username"],
            monitor_id=monitor_id,
            monitor_name=config["name"],
            url=config["url"],
            error=error_message,
        )
    else:
        logger.error(
            "alert_failed",
            alert_type=alert_type,
            user=config["username"],
            monitor_id=monitor_id,
        )

    return {
        "status": "sent" if success else "failed",
        "monitor_id": monitor_id,
        "alert_type": alert_type,
        "user": config["username"],
    }


# =============================================================================
# TASK: Send recovery alert (transitions from ERROR to OK).
# =============================================================================


async def send_alert_recovery(ctx: dict[str, Any], monitor_id: int) -> dict[str, Any]:
    redis = ctx["redis"]
    notifier: TelegramNotifier = ctx["notifier"]

    config_key = f"monitor:{monitor_id}:config"
    config_raw = await redis.get(config_key)

    if not config_raw:
        logger.warning("recovery_alert_monitor_not_found", monitor_id=monitor_id)
        return {"status": "skipped", "reason": "not_found"}

    config = json.loads(config_raw)

    if not config["telegram_chat_id"]:
        logger.info(
            "recovery_alert_skipped_no_telegram",
            user=config["username"],
            monitor_id=monitor_id,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    message = get_predefined_message(
        alert_type=AlertType.RECOVERY,
        monitor_name=config["name"] or "",
        url=config["url"],
    )

    success = await notifier.send_message(config["telegram_chat_id"], message)

    if success:
        logger.info(
            "recovery_alert_sent",
            user=config["username"],
            monitor_id=monitor_id,
            monitor_name=config["name"],
            url=config["url"],
        )
    else:
        logger.error(
            "recovery_alert_failed",
            user=config["username"],
            monitor_id=monitor_id,
        )

    return {
        "status": "sent" if success else "failed",
        "monitor_id": monitor_id,
        "user": config["username"],
    }


# =============================================================================
# TASK: Check single monitor
# =============================================================================


async def check_monitor(ctx: dict[str, Any], monitor_id: int) -> dict[str, Any]:
    http_client: httpx.AsyncClient = ctx["http_client"]
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    alert_type: str | None = None

    FAILURE_THRESHOLD = 2

    config_key = f"monitor:{monitor_id}:config"
    config_raw = await redis.get(config_key)

    if config_raw:
        config = json.loads(config_raw)

        if not config.get("is_active", True):
            logger.debug("monitor_paused", monitor_id=monitor_id, url=config["url"])
            return {"status": "skipped", "reason": "paused"}

        monitor_url = config["url"]
        monitor_method = config["method"]
        monitor_headers = config.get("headers") or {}
        monitor_body = config.get("body")
        monitor_name = config.get("name")
        user_id = config["user_id"]
    else:
        # Fallback to DB if config not in Redis (shouldn't happen normally)
        async with session_factory() as session:
            monitor = await session.get(Monitor, monitor_id)

            if not monitor:
                logger.warning("monitor_not_found", monitor_id=monitor_id)
                return {"status": "skipped", "reason": "not_found"}

            if not monitor.is_active:
                logger.debug("monitor_paused", monitor_id=monitor_id, url=monitor.url)
                return {"status": "skipped", "reason": "paused"}

            monitor_url = monitor.url
            monitor_method = monitor.method
            monitor_headers = monitor.headers or {}
            monitor_body = monitor.body
            monitor_name = monitor.name
            user_id = monitor.user_id

    state_key = f"monitor:{monitor_id}:state"
    cached_state = await redis.get(state_key)

    if cached_state is None:
        previous_status = None
    else:
        # Redis returns bytes, need to decode or compare with bytes
        previous_status = True if cached_state.decode() == "1" else False

    logger.debug(
        "check_started",
        monitor_id=monitor_id,
        url=monitor_url,
        previous_status=previous_status,
    )

    start_time = datetime.now(timezone.utc)
    status_code = None
    is_success = False
    error_message = None

    try:
        # body and head placeholder
        response = await http_client.request(
            method=monitor_method,
            url=monitor_url,
            headers=monitor_headers,
        )

        status_code = response.status_code
        is_success = 200 <= status_code < 400

    except httpx.TimeoutException:
        error_message = "Timeout: the site did not respond within 10 seconds"
        alert_type = "timeout"
        logger.warning("check_timeout", monitor_id=monitor_id, url=monitor_url)

    except httpx.ConnectError as e:
        error_message = f"Connection error: {str(e)}"
        alert_type = "connection"
        logger.warning(
            "check_connection_error",
            monitor_id=monitor_id,
            url=monitor_url,
            error=str(e),
        )

    except httpx.RequestError as e:
        error_message = f"Request error: {str(e)}"
        alert_type = "request"
        logger.error(
            "check_request_error",
            monitor_id=monitor_id,
            url=monitor_url,
            error=str(e),
        )

    end_time = datetime.now(timezone.utc)
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    async with session_factory() as session:
        log_entry = ResultLog(
            monitor_id=monitor_id,
            start_time=start_time,
            duration_ms=duration_ms,
            status_code=status_code,
            is_success=is_success,
            error_message=error_message,
        )
        session.add(log_entry)
        await session.commit()

    # Read old timestamp BEFORE updating (needed for recovery check)
    timestamp_key = f"monitor:{monitor_id}:last_check_time"
    old_timestamp_raw = await redis.get(timestamp_key)

    await redis.setex(state_key, 86400, "1" if is_success else "0")
    await redis.setex(timestamp_key, 86400, str(int(start_time.timestamp())))

    failure_key = f"monitor:{monitor_id}:failures"

    if is_success:
        # Success - reset failure counter
        current_failures = await redis.get(failure_key)
        if current_failures:
            await redis.delete(failure_key)
            logger.debug("failure_counter_reset", monitor_id=monitor_id)

        # Check for state transition: ERROR -> OK (recovery)
        # Only send recovery alert if we know previous state was ERROR (not None)
        if previous_status is False:
            # Check if this is a real recovery (last check was recent)
            # vs restored state from old DB logs (after worker restart)
            should_send_recovery = True

            if old_timestamp_raw is None:
                # No previous timestamp = first check after worker startup
                # This is a restored state from DB, not a real recovery
                should_send_recovery = False
                logger.info(
                    "recovery_suppressed_first_check",
                    monitor_id=monitor_id,
                    reason="no_previous_timestamp",
                )
            elif old_timestamp_raw:
                old_timestamp = int(old_timestamp_raw)
                time_since_last_check = start_time.timestamp() - old_timestamp

                # If last check was >1 hour ago, this is likely a stale state from DB
                # Don't send recovery alert (avoid false positives after restart)
                if time_since_last_check > 3600:
                    should_send_recovery = False
                    logger.info(
                        "recovery_suppressed_stale_state",
                        monitor_id=monitor_id,
                        time_since_last_check=int(time_since_last_check),
                        reason="last_check_too_old",
                    )

            if should_send_recovery:
                await redis.enqueue_job(
                    "send_alert_recovery",
                    monitor_id,
                )
                logger.info(
                    "recovery_alert_queued", monitor_id=monitor_id, url=monitor_url
                )
        elif previous_status is None:
            logger.debug(
                "first_successful_check",
                monitor_id=monitor_id,
                reason="no_previous_state",
            )

    else:
        # Failure - increment counter
        current_failures = await redis.get(failure_key)
        failure_count = int(current_failures) if current_failures else 0
        failure_count += 1

        # Store with TTL (e.g., 1 hour) to auto-cleanup old counters
        await redis.setex(failure_key, 3600, str(failure_count))

        logger.info(
            "failure_detected",
            monitor_id=monitor_id,
            failure_count=failure_count,
            threshold=FAILURE_THRESHOLD,
            previous_status=previous_status,
        )

        # Only send alert if:
        # 1. Failure count >= threshold (anti-flapping)
        # 2. OR this is first failure after being OK (state transition OK -> ERROR)
        should_alert = failure_count >= FAILURE_THRESHOLD or (
            previous_status is True and failure_count == 1
        )

        if should_alert:
            if alert_type:
                # Exception-based error (timeout, connection error, request error)
                await redis.enqueue_job(
                    "send_alert_exception",
                    monitor_id,
                    alert_type,
                    error_message,
                )
                logger.info(
                    "alert_queued",
                    alert_type=alert_type,
                    monitor_id=monitor_id,
                    failure_count=failure_count,
                )

            elif status_code is not None:
                # HTTP error (got response but status is 4xx or 5xx)
                await redis.enqueue_job(
                    "send_alert_http_error",
                    monitor_id,
                )
                logger.info(
                    "alert_queued",
                    alert_type="http_error",
                    monitor_id=monitor_id,
                    status_code=status_code,
                    failure_count=failure_count,
                )
        else:
            logger.info(
                "alert_suppressed",
                monitor_id=monitor_id,
                failure_count=failure_count,
                threshold=FAILURE_THRESHOLD,
                reason="anti_flapping",
            )

    next_run_score = await redis.zscore("scheduler", str(monitor_id))
    next_check_iso = None
    if next_run_score:
        next_check_iso = datetime.fromtimestamp(
            next_run_score, tz=timezone.utc
        ).isoformat()

    logger.info(
        "check_completed",
        monitor_id=monitor_id,
        url=monitor_url,
        is_success=is_success,
        status_code=status_code,
        duration_ms=duration_ms,
        next_check=next_check_iso,
        state_transition=f"{previous_status} -> {is_success}",
    )

    return {
        "status": "completed",
        "monitor_id": monitor_id,
        "url": monitor_url,
        "is_success": is_success,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }


# =============================================================================
# CRON JOB: Scheduler
# =============================================================================


async def scheduler(ctx: dict[str, Any]) -> None:
    """Scheduler that processes due monitors and enqueues check tasks."""
    redis = ctx["redis"]
    session_factory = ctx["session_factory"]

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

    due_monitors = await redis.zrangebyscore(
        "scheduler", min="-inf", max=now_ts, start=0, num=100
    )

    if not due_monitors:
        logger.debug("scheduler_idle")
        return

    logger.info("scheduler_processing", count=len(due_monitors))

    for monitor_id_raw in due_monitors:
        monitor_id = int(monitor_id_raw)

        await redis.enqueue_job("check_monitor", monitor_id)

        interval_key = f"monitor:{monitor_id}:interval"
        interval_raw = await redis.get(interval_key)

        if interval_raw:
            interval = int(interval_raw)
            next_run = now_ts + interval
            await redis.zadd("scheduler", {str(monitor_id): next_run})
        else:
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
                    logger.info("scheduler_paused_task_removed", monitor_id=monitor_id)
                    await redis.zrem("scheduler", str(monitor_id))
                    continue

                await redis.set(interval_key, monitor.interval)

                next_run = now_ts + monitor.interval
                await redis.zadd("scheduler", {str(monitor_id): next_run})

    logger.debug("scheduler_completed", queued_count=len(due_monitors))


# =============================================================================
# ARQ WORKER SETTINGS
# =============================================================================


class WorkerSettings:
    """
    Main ARQ worker configuration.
    ARQ reads this class at startup: arq src.worker.main.WorkerSettings

    CRON SYNTAX:
    cron(func, second=0)        — every minute at 0 seconds
    cron(func, minute=0)        — every hour at 0 minutes
    cron(func, second={0, 30})  — every 30 seconds
    """

    redis_settings = settings.redis.arq_settings
    functions = [
        check_monitor,
        send_alert_http_error,
        send_alert_exception,
        send_alert_recovery,
    ]
    cron_jobs = [
        cron(
            scheduler,
            second={0, 15, 30, 45},  # Every 15 seconds for better UX
            unique=True,  # Do not start a new one until the old one is finished
        )
    ]

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown

    max_jobs = 20
    job_timeout = 60

    max_tries = 3
