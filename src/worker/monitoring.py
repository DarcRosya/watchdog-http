from datetime import datetime, timezone
from typing import Any
import json

import httpx
from src.config.settings import settings
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog
from src.worker.lifecycle import (
    startup_monitoring,
    shutdown,
    logger,
)

# Queue name constants for cross-worker job routing
ALERTING_QUEUE = "arq:alerting"

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
        username = config.get("username")
        telegram_chat_id = config.get("telegram_chat_id")
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

            # Fetch user data for alerting
            from src.models.user import User

            user = await session.get(User, monitor.user_id)

            monitor_url = monitor.url
            monitor_method = monitor.method
            monitor_headers = monitor.headers or {}
            monitor_body = monitor.body
            monitor_name = monitor.name
            username = user.username if user else "unknown"
            telegram_chat_id = user.telegram_chat_id if user else None

            config = {
                "url": monitor_url,
                "method": monitor_method,
                "headers": monitor_headers,
                "body": monitor_body,
                "is_active": monitor.is_active,
                "name": monitor_name,
                "user_id": monitor.user_id,
                "username": username,
                "telegram_chat_id": telegram_chat_id,
            }
            await redis.setex(config_key, 86400, json.dumps(config))
            await redis.set(f"monitor:{monitor_id}:interval", monitor.interval)

            logger.info(
                "cache_repopulated_from_fallback",
                monitor_id=monitor_id,
                url=monitor_url,
            )

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

    request_kwargs = {
        "method": monitor_method,
        "url": monitor_url,
        "headers": monitor_headers,
    }

    if (
        monitor_body
        and isinstance(monitor_method, str)
        and monitor_method.upper() in ["POST", "PUT", "PATCH", "DELETE"]
    ):
        if isinstance(monitor_body, (bytes, bytearray)):
            request_kwargs["content"] = monitor_body
        else:
            request_kwargs["content"] = (
                monitor_body.encode("utf-8")
                if isinstance(monitor_body, str)
                else str(monitor_body).encode("utf-8")
            )

    try:
        # body and head placeholder
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

    except httpx.RequestError as e:
        error_message = f"Request error: {str(e)}"
        alert_type = "request"
        logger.error(
            "check_request_error",
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
                    telegram_chat_id,
                    username,
                    monitor_id,
                    monitor_name,
                    monitor_url,
                    _queue_name=ALERTING_QUEUE,
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
                    telegram_chat_id,
                    username,
                    monitor_id,
                    monitor_name,
                    monitor_url,
                    alert_type,
                    error_message,
                    _queue_name=ALERTING_QUEUE,
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
                    telegram_chat_id,
                    username,
                    monitor_id,
                    monitor_name,
                    monitor_url,
                    status_code,
                    duration_ms,
                    _queue_name=ALERTING_QUEUE,
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


class MonitoringWorkerSettings:
    """
    Monitoring Worker configuration for ARQ.

    This worker handles:
    - Checking monitors (HTTP requests)
    - Enqueuing alerts to alerting worker queue
    """

    queue_name = "arq:monitoring"
    redis_settings = settings.redis.arq_settings

    functions = [check_monitor]

    cron_jobs: list = []

    on_startup = startup_monitoring
    on_shutdown = shutdown

    max_jobs = 50  # High concurrency for HTTP checks
    job_timeout = 60  # Allow slow endpoints to respond
    max_tries = 2  # Retry once on failure
