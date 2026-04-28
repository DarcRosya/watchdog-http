import asyncio
import time
import socket
from typing import Any, Final

import httpx
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    push_to_gateway,  # type: ignore
)

from src.core.logging import get_logger

worker_registry: Final[Any] = CollectorRegistry()

INSTANCE_ID: Final[str] = socket.gethostname()

_push_lock: Final[asyncio.Lock] = asyncio.Lock()
_last_push_monotonic: float = 0.0
_min_push_interval_seconds: Final[float] = 5.0

SCHEDULER_BACKLOG: Final[Any] = Gauge(
    "scheduler_backlog",
    "Number of due monitors waiting to be scheduled",
    registry=worker_registry,
)

QUEUE_DEPTH: Final[Any] = Gauge(
    "arq_queue_depth",
    "Number of jobs currently in the ARQ queue",
    ["queue_name"],
    registry=worker_registry,
)

WORKER_JOBS_TOTAL: Final[Any] = Counter(
    "worker_jobs_total",
    "Total number of executed ARQ jobs",
    ["worker_type", "status"],  # (success/error)
    registry=worker_registry,
)

HTTP_CHECKS_TOTAL: Final[Any] = Counter(
    "http_checks_total",
    "Total HTTP checks performed",
    ["monitor_id", "status_code", "is_success"],  # 200, 404, 500 etc.
    registry=worker_registry,
)

CHECK_DURATION_SECONDS: Final[Any] = Histogram(
    "http_check_duration_seconds",
    "Time spent making the HTTP request",
    ["monitor_id"],
    registry=worker_registry,
)


async def push_metrics_async(
    pushgateway_url: str = "pushgateway:9091", job_name: str = "arq_worker"
) -> None:
    """Push collected metrics to Prometheus Pushgateway."""
    logger = get_logger("worker")

    global _last_push_monotonic

    async with _push_lock:
        now = time.monotonic()
        if now - _last_push_monotonic < _min_push_interval_seconds:
            return
        _last_push_monotonic = now

    def _push() -> None:
        try:
            push_to_gateway(
                pushgateway_url,
                job=job_name,
                registry=worker_registry,
                grouping_key={"instance": INSTANCE_ID},
            )
            logger.info(
                "metrics_pushed",
                pushgateway_url=pushgateway_url,
                job_name=job_name,
                instance=INSTANCE_ID,
            )
        except Exception as e:
            logger.error(
                "metrics_push_failed",
                pushgateway_url=pushgateway_url,
                job_name=job_name,
                instance=INSTANCE_ID,
                error=str(e),
                error_type=type(e).__name__,
            )

    await asyncio.to_thread(_push)


async def delete_metrics_from_gateway(
    pushgateway_host: str = "pushgateway:9091", job_name: str = "arq_worker"
) -> None:
    """
    Sends a DELETE request to Pushgateway before stopping the worker,
    to prevent "zombie metrics" from a dead container.
    """
    logger = get_logger("worker")

    url = f"http://{pushgateway_host}/metrics/job/{job_name}/instance/{INSTANCE_ID}"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.delete(url)
            response.raise_for_status()
            logger.info(
                "metrics_deleted_from_gateway",
                instance=INSTANCE_ID,
                status=response.status_code,
            )
    except Exception as e:
        logger.error(
            "metrics_delete_failed", instance=INSTANCE_ID, error=str(e), url=url
        )
