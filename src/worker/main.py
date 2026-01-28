from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from arq import cron
from sqlalchemy import select, update

from src.config.settings import settings
from src.core.database import async_session_factory
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog
from src.models.user import User
from src.telegram.notifier import (
    TelegramNotifier,
    AlertType,
    get_predefined_message,
)


def get_next_aligned_time(interval_seconds: int = 60) -> datetime:
    now = datetime.now(timezone.utc)
    aligned_now = now.replace(second=0, microsecond=0)

    return aligned_now + timedelta(seconds=interval_seconds)


async def startup(ctx: dict[str, Any]) -> None:
    print("=" * 60)
    print("🚀 WORKER STARTING UP")
    print("=" * 60)

    ctx["http_client"] = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=True, 
    )

    ctx["session_factory"] = async_session_factory
    
    # reuses http_client
    ctx["notifier"] = TelegramNotifier(http_client=ctx["http_client"])

    print(f"📊 Database: {settings.db.HOST}:{settings.db.PORT}")
    print(f"📮 Redis: {settings.redis.R_HOST}:{settings.redis.R_PORT}")
    print("📱 Telegram notifier: enabled")
    print("✅ Worker ready to process tasks!")
    print("=" * 60)


async def shutdown(ctx: dict[str, Any]) -> None:
    print("=" * 60)
    print("🛑 WORKER SHUTTING DOWN")
    print("=" * 60)

    http_client: httpx.AsyncClient = ctx.get("http_client")
    if http_client:
        await http_client.aclose()
        print("✅ HTTP client closed")

    print("👋 Worker stopped gracefully")
    print("=" * 60)


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
            print(f"⚠️ Monitor {monitor_id} not found for alert")
            return {"status": "skipped", "reason": "not_found"}

        monitor, user = row

        if not user.telegram_chat_id:
            print(f"📵 User {user.username} has no Telegram linked, skipping notification")
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
            print(f"📤 Alert sent to {user.username} for monitor {monitor.name or monitor.url}")
        else:
            print(f"⚠️ Failed to send alert to {user.username}")

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
    error_message: str | None = None
) -> dict[str, Any]:
    """
    Send notification about connection/timeout/request errors.
    These errors don't depend on log data, just the error type.
    """
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
            print(f"⚠️ Monitor {monitor_id} not found for alert")
            return {"status": "skipped", "reason": "not_found"}

        monitor, user = row

        if not user.telegram_chat_id:
            print(f"📵 User {user.username} has no Telegram linked, skipping notification")
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
            print(f"📤 Exception alert ({alert_type}) sent to {user.username}")
        else:
            print(f"⚠️ Failed to send exception alert to {user.username}")

        return {
            "status": "sent" if success else "failed",
            "monitor_id": monitor_id,
            "alert_type": alert_type,
            "user": user.username,
        }


# =============================================================================
# TASK: Check single monitor
# =============================================================================

async def check_monitor(ctx: dict[str, Any], monitor_id: int) -> dict[str, Any]:
    http_client: httpx.AsyncClient = ctx["http_client"]
    session_factory = ctx["session_factory"]
    
    # Track what type of error occurred for notifications
    alert_type: str | None = None
    
    async with session_factory() as session:
        query = select(Monitor).where(Monitor.id == monitor_id)
        result = await session.execute(query)
        monitor = result.scalars().first()

        if not monitor:
            print(f"⚠️ Monitor {monitor_id} not found, skipping")
            return {"status": "skipped", "reason": "not_found"}

        if not monitor.is_active:
            print(f"⏸️ Monitor {monitor_id} is paused, skipping")
            return {"status": "skipped", "reason": "paused"}

        print(f"🔍 Checking: {monitor.url}")

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
            print(f"⏱️ {monitor.url} — TIMEOUT")

        except httpx.ConnectError as e:
            error_message = f"Connection error: {str(e)}"
            alert_type = "connection"
            print(f"🔌 {monitor.url} — CONNECTION ERROR: {e}")

        except httpx.RequestError as e:
            error_message = f"Request error: {str(e)}"
            alert_type = "request"
            print(f"❌ {monitor.url} — ERROR: {e}")

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

        next_check = get_next_aligned_time(monitor.interval) # logs

        # Use update() instead of modifying the object
        # This is an atomic operation safer in case of concurrent access
        await session.execute(
            update(Monitor)
            .where(Monitor.id == monitor_id)
            .values(last_check_status=is_success)
        )

        await session.commit()

        if alert_type:
            # Exception-based error (timeout, connection error, request error)
            # No need to check logs, just send pre-formatted message
            await ctx["redis"].enqueue_job(
                "send_alert_exception",
                monitor_id,
                alert_type,
                error_message,
            )
            print(f"📨 Queued {alert_type} alert for monitor {monitor_id}")

        elif not is_success and status_code is not None:
            # HTTP error (got response but status is 4xx or 5xx)
            # Queue task that will fetch logs and notify user
            await ctx["redis"].enqueue_job(
                "send_alert_http_error",
                monitor_id,
            )
            print(f"📨 Queued HTTP error alert for monitor {monitor_id} (status: {status_code})")

        status_emoji = "✅" if is_success else "❌"
        print(
            f"{status_emoji} {monitor.url} — "
            f"status={status_code}, "
            f"duration={duration_ms}ms, "
            f"next_check={next_check.strftime('%H:%M:%S')}"
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
    
    print("\n" + "─" * 40)
    print(f"⏰ Scheduler running at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
    
    async with session_factory() as session:
        # Get monitors that are due for checking
        now = datetime.now(timezone.utc)
        
        query = (
            select(Monitor)
            .where(
                Monitor.is_active == True,  # noqa: E712 
                Monitor.next_check_at <= now
            )
            .limit(100) 
        )
        
        result = await session.execute(query)
        monitors = result.scalars().all()
        
        if not monitors:
            print("📭 No monitors due for checking")
            print("─" * 40)
            return
        
        print(f"📋 Found {len(monitors)} monitors to check")

        for monitor in monitors:
            await ctx["redis"].enqueue_job("check_monitor", monitor.id)

            next_aligned_time = get_next_aligned_time(monitor.interval)

            print(f"  📤 Queued: {monitor.name or monitor.url}")
            
            # Update next_check_at immediately to avoid duplicates.
            # Even if the task fails, the next scheduler will create it again.
            await session.execute(
                update(Monitor)
                .where(Monitor.id == monitor.id)
                .values(next_check_at=next_aligned_time)
            )
        
        await session.commit()
        print("─" * 40)


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
