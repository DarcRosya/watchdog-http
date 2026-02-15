"""Alerting worker: Telegram notifications for monitor failures and recoveries."""
from typing import Any
import json

from sqlalchemy import select

from src.config.settings import settings
from src.models.resultlog import ResultLog
from src.telegram.notifier import (
    TelegramNotifier,
    AlertType,
    get_predefined_message,
)
from src.worker.lifecycle import (
    startup_alerting,
    shutdown,
    logger,
)

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


class AlertingWorkerSettings:
    """
    Alerting Worker configuration for ARQ.

    This worker handles:
    - Sending HTTP error alerts
    - Sending exception alerts (timeout, connection errors)
    - Sending recovery alerts
    """

    redis_settings = settings.redis.arq_settings

    functions = [
        send_alert_http_error,
        send_alert_exception,
        send_alert_recovery,
    ]

    # No cron jobs - alerts are triggered by monitoring worker
    cron_jobs: list = []

    on_startup = startup_alerting
    on_shutdown = shutdown

    max_jobs = 30  # Moderate concurrency for Telegram API
    job_timeout = 30  # Telegram API timeout
    max_tries = 3  # Retry on network failures
