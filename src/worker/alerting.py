from typing import Any

from src.core.settings import settings
from src.telegram.notifier import (
    AlertType,
    TelegramNotifier,
    get_predefined_message,
)
from src.worker.lifecycle import (
    AlertingWorkerContext,
    logger,
    on_job_complete,
    shutdown,
    startup_alerting,
)
from src.worker.metrics import WORKER_JOBS_TOTAL

# =============================================================================
# TASK: Send Telegram message
# =============================================================================


async def send_telegram_message(
    ctx: AlertingWorkerContext,
    chat_id: int,
    message: str,
    alert_metadata: dict[str, Any],
) -> dict[str, Any]:
    notifier: TelegramNotifier = ctx["notifier"]

    success = await notifier.send_message(chat_id, message)

    if success:
        logger.info(
            "telegram_message_sent",
            **alert_metadata,
        )
        WORKER_JOBS_TOTAL.labels(
            worker_type="send_telegram_message",
            status="success",
        ).inc()
    else:
        logger.error(
            "telegram_message_failed",
            **alert_metadata,
        )
        WORKER_JOBS_TOTAL.labels(
            worker_type="send_telegram_message",
            status="error",
        ).inc()

    return {
        "status": "sent" if success else "failed",
        **alert_metadata,
    }


# =============================================================================
# TASK: Send HTTP error alert
# =============================================================================


async def send_alert_http_error(
    ctx: AlertingWorkerContext,
    chat_id: int,
    username: str,
    monitor_id: int,
    monitor_name: str,
    monitor_url: str,
    status_code: int,
    duration_ms: int,
) -> dict[str, Any]:
    redis = ctx["redis"]

    if not chat_id:
        logger.info(
            "http_alert_skipped_no_telegram",
            user=username,
            monitor_id=monitor_id,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    message = get_predefined_message(
        alert_type=AlertType.HTTP_ERROR,
        monitor_name=monitor_name or "",
        url=monitor_url,
        status_code=status_code,
        duration_ms=duration_ms,
    )

    # Enqueue message sending
    alert_metadata: dict[str, str | int | None] = {
        "alert_type": "http_error",
        "monitor_id": monitor_id,
        "user": username,
        "monitor_name": monitor_name,
        "url": monitor_url,
    }

    await redis.enqueue_job(
        "send_telegram_message",
        chat_id,
        message,
        alert_metadata,
    )

    logger.info("alert_queued", **alert_metadata)

    return {
        "status": "queued",
        "monitor_id": monitor_id,
        "user": username,
    }


# =============================================================================
# TASK: Send exception-based alert
# =============================================================================


async def send_alert_exception(
    ctx: AlertingWorkerContext,
    chat_id: int,
    username: str,
    monitor_id: int,
    monitor_name: str,
    monitor_url: str,
    alert_type: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    redis = ctx["redis"]

    alert_type_map = {
        "timeout": AlertType.TIMEOUT,
        "connection": AlertType.CONNECTION_ERROR,
        "request": AlertType.REQUEST_ERROR,
    }
    alert_enum = alert_type_map.get(alert_type, AlertType.REQUEST_ERROR)

    if not chat_id:
        logger.info(
            "alert_skipped_no_telegram",
            user=username,
            monitor_id=monitor_id,
            alert_type=alert_type,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    message = get_predefined_message(
        alert_type=alert_enum,
        monitor_name=monitor_name or "",
        url=monitor_url,
        error=error_message,
    )

    # Enqueue message sending
    alert_metadata: dict[str, str | int | None] = {
        "alert_type": alert_type,
        "monitor_id": monitor_id,
        "user": username,
        "monitor_name": monitor_name,
        "url": monitor_url,
        "error": error_message,
    }

    await redis.enqueue_job(
        "send_telegram_message",
        chat_id,
        message,
        alert_metadata,
    )

    logger.info("alert_queued", **alert_metadata)

    return {
        "status": "queued",
        "monitor_id": monitor_id,
        "alert_type": alert_type,
        "user": username,
    }


# =============================================================================
# TASK: Send recovery alert
# =============================================================================


async def send_alert_recovery(
    ctx: AlertingWorkerContext,
    chat_id: int,
    username: str,
    monitor_id: int,
    monitor_name: str,
    monitor_url: str,
) -> dict[str, Any]:
    """Send recovery alert with all data passed directly from monitoring worker."""
    redis = ctx["redis"]

    if not chat_id:
        logger.info(
            "recovery_alert_skipped_no_telegram",
            user=username,
            monitor_id=monitor_id,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    message = get_predefined_message(
        alert_type=AlertType.RECOVERY,
        monitor_name=monitor_name or "",
        url=monitor_url,
    )

    # Enqueue message sending
    alert_metadata: dict[str, str | int | None] = {
        "alert_type": "recovery",
        "monitor_id": monitor_id,
        "user": username,
        "monitor_name": monitor_name,
        "url": monitor_url,
    }

    await redis.enqueue_job(
        "send_telegram_message",
        chat_id,
        message,
        alert_metadata,
    )

    logger.info("alert_queued", **alert_metadata)

    return {
        "status": "queued",
        "monitor_id": monitor_id,
        "user": username,
    }


# =============================================================================
# TASK: Send SSL certificate expiry alert
# =============================================================================


async def send_alert_ssl_expiry(
    ctx: AlertingWorkerContext,
    chat_id: int,
    username: str,
    monitor_id: int,
    monitor_name: str,
    monitor_url: str,
    days_left: int,
) -> dict[str, Any]:
    """Send alert when SSL certificate is expiring within 7 days."""
    redis = ctx["redis"]

    if not chat_id:
        logger.info(
            "ssl_alert_skipped_no_telegram",
            user=username,
            monitor_id=monitor_id,
        )
        return {"status": "skipped", "reason": "no_telegram"}

    message = get_predefined_message(
        alert_type=AlertType.SSL_EXPIRY,
        monitor_name=monitor_name or "",
        url=monitor_url,
        days_left=days_left,
    )

    alert_metadata: dict[str, str | int | None] = {
        "alert_type": "ssl_expiry",
        "monitor_id": monitor_id,
        "user": username,
        "monitor_name": monitor_name,
        "url": monitor_url,
        "days_left": days_left,
    }

    await redis.enqueue_job(
        "send_telegram_message",
        chat_id,
        message,
        alert_metadata,
    )

    logger.info("alert_queued", **alert_metadata)

    return {
        "status": "queued",
        "monitor_id": monitor_id,
        "user": username,
        "days_left": days_left,
    }


class AlertingWorkerSettings:
    """
    Alerting Worker configuration for ARQ.

    This worker handles:
    - Sending HTTP error alerts
    - Sending exception alerts (timeout, connection errors)
    - Sending recovery alerts
    - Sending SSL certificate expiry alerts
    """

    queue_name = "arq:alerting"
    redis_settings = settings.redis.arq_settings

    functions: list[Any] = [
        send_telegram_message,
        send_alert_http_error,
        send_alert_exception,
        send_alert_recovery,
        send_alert_ssl_expiry,
    ]

    # No cron jobs - alerts are triggered by monitoring worker
    cron_jobs: list[Any] = []

    on_startup = startup_alerting
    on_shutdown = shutdown

    after_job_end = on_job_complete

    max_jobs = 15  # Moderate concurrency for Telegram API
    job_timeout = 30  # Telegram API timeout
    max_tries = 3  # Retry on network failures
