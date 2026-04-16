import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal, TypedDict, cast

import httpx
from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog
from src.models.user import User
from src.utils.ssl_checker import get_ssl_days_remaining
from src.worker.lifecycle import (
    MonitoringWorkerContext,
    logger,
    shutdown,
    startup_monitoring,
)

# Queue name constants for cross-worker job routing
ALERTING_QUEUE = "arq:alerting"


class MonitorRuntimeConfig(TypedDict):
    url: str
    method: str
    headers: dict[str, Any]
    body: Any
    is_active: bool
    name: str | None
    user_id: int
    username: str
    telegram_chat_id: int | None


class SkippedMonitorConfig(TypedDict):
    status: Literal["skipped"]
    reason: Literal["paused", "not_found"]


@dataclass
class HttpCheckResult:
    """Result of a single HTTP check against a monitor endpoint."""

    start_time: datetime
    duration_ms: int
    status_code: int | None
    is_success: bool
    error_message: str | None
    alert_type: str | None


# =============================================================================
# STEP 1: Resolve monitor config (Redis cache → DB fallback)
# =============================================================================


async def get_monitor_config(
    redis: ArqRedis,
    session_factory: Callable[[], AsyncSession],
    monitor_id: int,
) -> MonitorRuntimeConfig | SkippedMonitorConfig:
    """Load monitor configuration from Redis cache with DB fallback."""
    config_key = f"monitor:{monitor_id}:config"
    config_raw = await redis.get(config_key)

    if config_raw:
        config = cast(MonitorRuntimeConfig, json.loads(config_raw))

        if not config.get("is_active", True):
            logger.debug("monitor_paused", monitor_id=monitor_id, url=config["url"])
            return {"status": "skipped", "reason": "paused"}

        return config

    # Fallback to DB if config not in Redis (shouldn't happen normally)
    async with session_factory() as session:
        monitor = await session.get(Monitor, monitor_id)

        if not monitor:
            logger.warning("monitor_not_found", monitor_id=monitor_id)
            return {"status": "skipped", "reason": "not_found"}

        if not monitor.is_active:
            logger.debug("monitor_paused", monitor_id=monitor_id, url=monitor.url)
            return {"status": "skipped", "reason": "paused"}

        user = await session.get(User, monitor.user_id)

        db_config: MonitorRuntimeConfig = {
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
        await redis.setex(config_key, 86400, json.dumps(db_config))
        await redis.set(f"monitor:{monitor_id}:interval", monitor.interval)

        logger.info(
            "cache_repopulated_from_fallback",
            monitor_id=monitor_id,
            url=monitor.url,
        )

    return db_config


# =============================================================================
# STEP 2: Execute HTTP request
# =============================================================================


async def execute_http_check(
    http_client: httpx.AsyncClient,
    config: MonitorRuntimeConfig,
    monitor_id: int,
) -> HttpCheckResult:
    """Perform the actual HTTP request and return structured result."""
    alert_type: str | None = None
    status_code: int | None = None
    is_success = False
    error_message: str | None = None

    monitor_url = config["url"]
    monitor_method = config["method"]
    monitor_headers = cast(dict[str, str], config.get("headers") or {})
    monitor_body = config.get("body")

    request_kwargs: dict[str, Any] = {
        "method": monitor_method,
        "url": monitor_url,
        "headers": monitor_headers,
    }

    if monitor_body and monitor_method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
        if isinstance(monitor_body, (bytes, bytearray)):
            request_kwargs["content"] = monitor_body
        else:
            request_kwargs["content"] = (
                monitor_body.encode("utf-8")
                if isinstance(monitor_body, str)
                else str(monitor_body).encode("utf-8")
            )

    start_time = datetime.now(timezone.utc)

    try:
        response = await http_client.request(**request_kwargs)
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

    except httpx.LocalProtocolError as e:
        error_message = f"Protocol error (check headers/body): {str(e)}"
        alert_type = "request"
        logger.error(
            "check_protocol_error",
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

    return HttpCheckResult(
        start_time=start_time,
        duration_ms=duration_ms,
        status_code=status_code,
        is_success=is_success,
        error_message=error_message,
        alert_type=alert_type,
    )


# =============================================================================
# STEP 3: Persist result log to DB
# =============================================================================


async def persist_result_log(
    session_factory: Callable[[], AsyncSession],
    monitor_id: int,
    result: HttpCheckResult,
) -> None:
    """Write the check result to the database."""
    async with session_factory() as session:
        log_entry = ResultLog(
            monitor_id=monitor_id,
            start_time=result.start_time,
            duration_ms=result.duration_ms,
            status_code=result.status_code,
            is_success=result.is_success,
            error_message=result.error_message,
        )
        session.add(log_entry)
        await session.commit()


# =============================================================================
# STEP 4: SSL certificate expiry check (once per day, HTTPS only)
# =============================================================================


async def check_ssl_expiry(
    redis: ArqRedis,
    monitor_id: int,
    config: MonitorRuntimeConfig,
) -> None:
    """Check SSL certificate expiry for HTTPS monitors (max once/day)."""
    monitor_url = config["url"]

    if not monitor_url.startswith("https"):
        return

    ssl_check_timer_key = f"monitor:{monitor_id}:ssl_checked_today"

    if await redis.exists(ssl_check_timer_key):
        return

    await redis.setex(ssl_check_timer_key, 86400, "1")

    days_left = await get_ssl_days_remaining(monitor_url)

    if days_left is not None and days_left <= 7:
        ssl_alert_sent_key = f"monitor:{monitor_id}:ssl_alert_sent"

        if not await redis.exists(ssl_alert_sent_key):
            await redis.setex(ssl_alert_sent_key, 86400, "1")

            await redis.enqueue_job(
                "send_alert_ssl_expiry",
                config.get("telegram_chat_id"),
                config.get("username"),
                monitor_id,
                config.get("name"),
                monitor_url,
                days_left,
                _queue_name=ALERTING_QUEUE,
            )
            logger.warning(
                "ssl_expiry_alert_queued",
                monitor_id=monitor_id,
                url=monitor_url,
                days_left=days_left,
            )
    elif days_left is not None:
        logger.debug(
            "ssl_certificate_ok",
            monitor_id=monitor_id,
            url=monitor_url,
            days_left=days_left,
        )


# =============================================================================
# STEP 5: Process alerting logic (failures, recovery, anti-flapping)
# =============================================================================

FAILURE_THRESHOLD = 2


async def process_alerting(
    redis: ArqRedis,
    monitor_id: int,
    config: MonitorRuntimeConfig,
    result: HttpCheckResult,
    previous_status: bool | None,
    old_timestamp_raw: bytes | None,
) -> None:
    """Handle failure counting, alert dispatch, and recovery detection."""
    monitor_url = config["url"]
    monitor_name = config.get("name")
    username = config.get("username")
    telegram_chat_id = config.get("telegram_chat_id")

    failure_key = f"monitor:{monitor_id}:failures"

    if result.is_success:
        # Success — reset failure counter
        current_failures = await redis.get(failure_key)
        if current_failures:
            await redis.delete(failure_key)
            logger.debug("failure_counter_reset", monitor_id=monitor_id)

        # State transition: ERROR → OK (recovery)
        if previous_status is False:
            should_send_recovery = True

            if old_timestamp_raw is None:
                should_send_recovery = False
                logger.info(
                    "recovery_suppressed_first_check",
                    monitor_id=monitor_id,
                    reason="no_previous_timestamp",
                )
            elif old_timestamp_raw:
                old_timestamp = int(old_timestamp_raw)
                time_since_last_check = result.start_time.timestamp() - old_timestamp

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
                    telegram_chat_id,
                    username,
                    monitor_id,
                    monitor_name,
                    monitor_url,
                    _queue_name=ALERTING_QUEUE,
                )
                logger.info(
                    "recovery_alert_queued",
                    monitor_id=monitor_id,
                    url=monitor_url,
                )

        elif previous_status is None:
            logger.debug(
                "first_successful_check",
                monitor_id=monitor_id,
                reason="no_previous_state",
            )

    else:
        # Failure — increment counter
        current_failures = await redis.get(failure_key)
        failure_count = int(current_failures) if current_failures else 0
        failure_count += 1

        await redis.setex(failure_key, 3600, str(failure_count))

        logger.info(
            "failure_detected",
            monitor_id=monitor_id,
            failure_count=failure_count,
            threshold=FAILURE_THRESHOLD,
            previous_status=previous_status,
        )

        should_alert = failure_count >= FAILURE_THRESHOLD or (
            previous_status is True and failure_count == 1
        )

        if should_alert:
            if result.alert_type:
                await redis.enqueue_job(
                    "send_alert_exception",
                    telegram_chat_id,
                    username,
                    monitor_id,
                    monitor_name,
                    monitor_url,
                    result.alert_type,
                    result.error_message,
                    _queue_name=ALERTING_QUEUE,
                )
                logger.info(
                    "alert_queued",
                    alert_type=result.alert_type,
                    monitor_id=monitor_id,
                    failure_count=failure_count,
                )

            elif result.status_code is not None:
                await redis.enqueue_job(
                    "send_alert_http_error",
                    telegram_chat_id,
                    username,
                    monitor_id,
                    monitor_name,
                    monitor_url,
                    result.status_code,
                    result.duration_ms,
                    _queue_name=ALERTING_QUEUE,
                )
                logger.info(
                    "alert_queued",
                    alert_type="http_error",
                    monitor_id=monitor_id,
                    status_code=result.status_code,
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


# =============================================================================
# TASK: Check single monitor (orchestrator)
# =============================================================================


async def check_monitor(
    ctx: MonitoringWorkerContext, monitor_id: int
) -> dict[str, Any]:
    """Top-level ARQ task that orchestrates a full monitor check cycle."""
    redis = ctx["redis"]

    # 1. Resolve config
    config = await get_monitor_config(redis, ctx["session_factory"], monitor_id)

    if "status" in config:
        return cast(dict[str, Any], config)

    runtime_config = config

    monitor_url = runtime_config["url"]

    # 2. Read previous state
    state_key = f"monitor:{monitor_id}:state"
    cached_state = await redis.get(state_key)

    if cached_state is None:
        previous_status = None
    else:
        previous_status = True if cached_state.decode() == "1" else False

    logger.debug(
        "check_started",
        monitor_id=monitor_id,
        url=monitor_url,
        previous_status=previous_status,
    )

    # 3. Execute HTTP check
    result = await execute_http_check(ctx["http_client"], runtime_config, monitor_id)

    # 4. Persist result to DB
    await persist_result_log(ctx["session_factory"], monitor_id, result)

    # 5. Update state in Redis (read old timestamp BEFORE updating)
    timestamp_key = f"monitor:{monitor_id}:last_check_time"
    old_timestamp_raw = await redis.get(timestamp_key)

    await redis.setex(state_key, 86400, "1" if result.is_success else "0")
    await redis.setex(timestamp_key, 86400, str(int(result.start_time.timestamp())))

    # 6. SSL expiry check
    await check_ssl_expiry(redis, monitor_id, runtime_config)

    # 7. Alerting (failures, recovery, anti-flapping)
    await process_alerting(
        redis,
        monitor_id,
        runtime_config,
        result,
        previous_status,
        old_timestamp_raw,
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
        is_success=result.is_success,
        status_code=result.status_code,
        duration_ms=result.duration_ms,
        next_check=next_check_iso,
        state_transition=f"{previous_status} -> {result.is_success}",
    )

    return {
        "status": "completed",
        "monitor_id": monitor_id,
        "url": monitor_url,
        "is_success": result.is_success,
        "status_code": result.status_code,
        "duration_ms": result.duration_ms,
    }


class MonitoringWorkerSettings:
    """
    Monitoring Worker configuration for ARQ.

    This worker handles:
    - Checking monitors (HTTP requests)
    - SSL certificate expiry checks
    - Enqueuing alerts to alerting worker queue
    """

    queue_name = "arq:monitoring"
    redis_settings = settings.redis.arq_settings

    functions = [check_monitor]

    cron_jobs: list[Any] = []

    on_startup = startup_monitoring
    on_shutdown = shutdown

    max_jobs = 50  # High concurrency for HTTP checks
    job_timeout = 60  # Allow slow endpoints to respond
    max_tries = 2  # Retry once on failure
