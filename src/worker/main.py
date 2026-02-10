from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from arq import cron
from sqlalchemy import select, update

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
    notifier: TelegramNotifier = ctx["notifier"]

    async with session_factory() as session:
        query = (
            select(Monitor, User)
            .join(User, Monitor.user_id == User.id)
            .where(Monitor.id == monitor_id)
        )
        result = await session.execute(query)
        row = result.first()

        if not row:
            logger.warning("http_alert_monitor_not_found", monitor_id=monitor_id)
            return {"status": "skipped", "reason": "not_found"}

        monitor, user = row

        if not user.telegram_chat_id:
            logger.info(
                "http_alert_skipped_no_telegram",
                user=user.username,
                monitor_id=monitor_id,
            )
            return {"status": "skipped", "reason": "no_telegram"}

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
            monitor_name=monitor.name or "",
            url=monitor.url,
            status_code=last_log.status_code if last_log else None,
            duration_ms=last_log.duration_ms if last_log else None,
        )

        success = await notifier.send_alert(user.telegram_chat_id, message)

        if success:
            logger.info(
                "alert_sent",
                alert_type="http_error",
                user=user.username,
                monitor_id=monitor_id,
                monitor_name=monitor.name,
                url=monitor.url,
            )
        else:
            logger.error(
                "alert_failed",
                alert_type="http_error",
                user=user.username,
                monitor_id=monitor_id,
            )

        return {
            "status": "sent" if success else "failed",
            "monitor_id": monitor_id,
            "user": user.username,
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
    session_factory = ctx["session_factory"]
    notifier: TelegramNotifier = ctx["notifier"]

    alert_type_map = {
        "timeout": AlertType.TIMEOUT,
        "connection": AlertType.CONNECTION_ERROR,
        "request": AlertType.REQUEST_ERROR,
    }
    alert_enum = alert_type_map.get(alert_type, AlertType.REQUEST_ERROR)

    async with session_factory() as session:
        query = (
            select(Monitor, User)
            .join(User, Monitor.user_id == User.id)
            .where(Monitor.id == monitor_id)
        )
        result = await session.execute(query)
        row = result.first()

        if not row:
            logger.warning(
                "alert_monitor_not_found", monitor_id=monitor_id, alert_type=alert_type
            )
            return {"status": "skipped", "reason": "not_found"}

        monitor, user = row

        if not user.telegram_chat_id:
            logger.info(
                "alert_skipped_no_telegram",
                user=user.username,
                monitor_id=monitor_id,
                alert_type=alert_type,
            )
            return {"status": "skipped", "reason": "no_telegram"}

        # Get pre-formatted message
        message = get_predefined_message(
            alert_type=alert_enum,
            monitor_name=monitor.name or "",
            url=monitor.url,
            error=error_message,
        )

        success = await notifier.send_message(user.telegram_chat_id, message)

        if success:
            logger.info(
                "alert_sent",
                alert_type=alert_type,
                user=user.username,
                monitor_id=monitor_id,
                monitor_name=monitor.name,
                url=monitor.url,
                error=error_message,
            )
        else:
            logger.error(
                "alert_failed",
                alert_type=alert_type,
                user=user.username,
                monitor_id=monitor_id,
            )

        return {
            "status": "sent" if success else "failed",
            "monitor_id": monitor_id,
            "alert_type": alert_type,
            "user": user.username,
        }


# =============================================================================
# TASK: Send recovery alert (transitions from ERROR to OK).
# =============================================================================


async def send_alert_recovery(ctx: dict[str, Any], monitor_id: int) -> dict[str, Any]:
    session_factory = ctx["session_factory"]
    notifier: TelegramNotifier = ctx["notifier"]

    async with session_factory() as session:
        query = (
            select(Monitor, User)
            .join(User, Monitor.user_id == User.id)
            .where(Monitor.id == monitor_id)
        )
        result = await session.execute(query)
        row = result.first()

        if not row:
            logger.warning("recovery_alert_monitor_not_found", monitor_id=monitor_id)
            return {"status": "skipped", "reason": "not_found"}

        monitor, user = row

        if not user.telegram_chat_id:
            logger.info(
                "recovery_alert_skipped_no_telegram",
                user=user.username,
                monitor_id=monitor_id,
            )
            return {"status": "skipped", "reason": "no_telegram"}

        message = get_predefined_message(
            alert_type=AlertType.RECOVERY,
            monitor_name=monitor.name or "",
            url=monitor.url,
        )

        success = await notifier.send_message(user.telegram_chat_id, message)

        if success:
            logger.info(
                "recovery_alert_sent",
                user=user.username,
                monitor_id=monitor_id,
                monitor_name=monitor.name,
                url=monitor.url,
            )
        else:
            logger.error(
                "recovery_alert_failed",
                user=user.username,
                monitor_id=monitor_id,
            )

        return {
            "status": "sent" if success else "failed",
            "monitor_id": monitor_id,
            "user": user.username,
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

    async with session_factory() as session:
        query = select(Monitor).where(Monitor.id == monitor_id)
        result = await session.execute(query)
        monitor = result.scalars().first()

        if not monitor:
            logger.warning("monitor_not_found", monitor_id=monitor_id)
            return {"status": "skipped", "reason": "not_found"}

        if not monitor.is_active:
            logger.debug("monitor_paused", monitor_id=monitor_id, url=monitor.url)
            return {"status": "skipped", "reason": "paused"}

        previous_status = monitor.last_check_status

        logger.debug(
            "check_started",
            monitor_id=monitor_id,
            url=monitor.url,
            previous_status=previous_status,
        )

        start_time = datetime.now(timezone.utc)
        status_code = None
        is_success = False
        error_message = None

        try:
            # body and head placeholder
            response = await http_client.request(
                method=monitor.method,
                url=monitor.url,
                headers=monitor.headers,
            )

            status_code = response.status_code
            is_success = 200 <= status_code < 400

        except httpx.TimeoutException:
            error_message = "Timeout: the site did not respond within 10 seconds"
            alert_type = "timeout"
            logger.warning("check_timeout", monitor_id=monitor_id, url=monitor.url)

        except httpx.ConnectError as e:
            error_message = f"Connection error: {str(e)}"
            alert_type = "connection"
            logger.warning(
                "check_connection_error",
                monitor_id=monitor_id,
                url=monitor.url,
                error=str(e),
            )

        except httpx.RequestError as e:
            error_message = f"Request error: {str(e)}"
            alert_type = "request"
            logger.error(
                "check_request_error",
                monitor_id=monitor_id,
                url=monitor.url,
                error=str(e),
            )

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        log_entry = ResultLog(
            monitor_id=monitor_id,
            start_time=start_time,
            duration_ms=duration_ms,
            status_code=status_code,
            is_success=is_success,
            error_message=error_message,
        )
        session.add(log_entry)

        next_check = get_next_aligned_time(monitor.interval)  # logs

        # Use update() instead of modifying the object
        # This is an atomic operation safer in case of concurrent access
        await session.execute(
            update(Monitor)
            .where(Monitor.id == monitor_id)
            .values(last_check_status=is_success)
        )

        await session.commit()

        failure_key = f"monitor:{monitor_id}:failures"

        if is_success:
            # Success - reset failure counter
            current_failures = await redis.get(failure_key)
            if current_failures:
                await redis.delete(failure_key)
                logger.debug("failure_counter_reset", monitor_id=monitor_id)

            # Check for state transition: ERROR -> OK (recovery)
            if previous_status is False:
                # Monitor recovered! Send recovery notification
                await redis.enqueue_job(
                    "send_alert_recovery",
                    monitor_id,
                )
                logger.info(
                    "recovery_alert_queued", monitor_id=monitor_id, url=monitor.url
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

        logger.info(
            "check_completed",
            monitor_id=monitor_id,
            url=monitor.url,
            is_success=is_success,
            status_code=status_code,
            duration_ms=duration_ms,
            next_check=next_check.isoformat(),
            state_transition=f"{previous_status} -> {is_success}",
        )

        return {
            "status": "completed",
            "monitor_id": monitor_id,
            "url": monitor.url,
            "is_success": is_success,
            "status_code": status_code,
            "duration_ms": duration_ms,
        }


# =============================================================================
# CRON JOB: Scheduler
# =============================================================================


async def scheduler(ctx: dict[str, Any]) -> None:
    session_factory = ctx["session_factory"]

    logger.debug("scheduler_started", timestamp=datetime.now(timezone.utc).isoformat())

    async with session_factory() as session:
        # Get monitors that are due for checking
        now = datetime.now(timezone.utc)

        query = (
            select(Monitor)
            .where(
                Monitor.is_active == True, Monitor.next_check_at <= now  # noqa: E712
            )
            .limit(100)
        )

        result = await session.execute(query)
        monitors = result.scalars().all()

        if not monitors:
            logger.debug("scheduler_no_monitors_due")
            return

        logger.info("scheduler_monitors_found", count=len(monitors))

        for monitor in monitors:
            await ctx["redis"].enqueue_job("check_monitor", monitor.id)

            next_aligned_time = get_next_aligned_time(monitor.interval)

            logger.debug(
                "monitor_queued",
                monitor_id=monitor.id,
                name=monitor.name,
                url=monitor.url,
            )

            # Update next_check_at immediately to avoid duplicates.
            # Even if the task fails, the next scheduler will create it again.
            await session.execute(
                update(Monitor)
                .where(Monitor.id == monitor.id)
                .values(next_check_at=next_aligned_time)
            )

        await session.commit()
        logger.debug("scheduler_completed", queued_count=len(monitors))


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
            second={0},
            unique=True,  # Do not start a new one until the old one is finished
        )
    ]

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown

    max_jobs = 20
    job_timeout = 60

    max_tries = 3
