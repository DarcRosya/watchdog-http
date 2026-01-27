from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from arq import cron
from sqlalchemy import select, update

from src.config.settings import settings
from src.core.database import async_session_factory
from src.models.monitor import Monitor
from src.models.resultlog import ResultLog


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

    print(f"📊 Database: {settings.db.HOST}:{settings.db.PORT}")
    print(f"📮 Redis: {settings.redis.R_HOST}:{settings.redis.R_PORT}")
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
# TASK: Check single monitor
# =============================================================================

async def check_monitor(ctx: dict[str, Any], monitor_id: int) -> dict[str, Any]:
    http_client: httpx.AsyncClient = ctx["http_client"]
    session_factory = ctx["session_factory"]
    
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
            print(f"⏱️ {monitor.url} — TIMEOUT")

        except httpx.ConnectError as e:
            error_message = f"Connection error: {str(e)}"
            print(f"🔌 {monitor.url} — CONNECTION ERROR: {e}")

        except httpx.RequestError as e:
            error_message = f"Request error: {str(e)}"
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

        next_check = datetime.now(timezone.utc) + timedelta(seconds=monitor.interval)

        # Use update() instead of modifying the object
        # This is an atomic operation safer in case of concurrent access
        await session.execute(
            update(Monitor)
            .where(Monitor.id == monitor_id)
            .values(
                next_check_at=next_check,
                last_check_status=is_success
            )
        )

        await session.commit()

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
    """
    Cron task: runs every minute.
    Reads all monitors from the database that are “due for checking”
    (next_check_at <= current time) and creates tasks for them.

    POTENTIAL PROBLEM: Duplicate tasks
    If one monitor is still being checked and the scheduler has already
    created a new task, we will get a duplicate.
    
    SOLUTION (simplified for now):
    - Update next_check_at immediately when creating a task
    - In production, a locking mechanism is required (Redis SETNX)
    """
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
            await ctx["redis"].enqueue_job(
                "check_monitor",  
                monitor.id,   
            )
            print(f"  📤 Queued: {monitor.name or monitor.url}")
            
            # Update next_check_at immediately to avoid duplicates.
            # Even if the task fails, the next scheduler will create it again.
            await session.execute(
                update(Monitor)
                .where(Monitor.id == monitor.id)
                .values(next_check_at=now + timedelta(seconds=monitor.interval))
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
    functions = [check_monitor]
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

    max_jobs = 10  
    job_timeout = 60  

    max_tries = 3
