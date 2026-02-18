from typing import List

from fastapi import APIRouter, HTTPException, status

from src.core.database import DBSession
from src.core.dependencies import CurrentUser, RedisClient
from src.core.logging import get_logger
from src.schemas.monitor import (
    MonitorCreate,
    MonitorResponse,
    MonitoringStatus,
    MonitorUpdate,
)
from src.services.monitor import MonitorService

logger = get_logger("api")
router = APIRouter(prefix="/monitors", tags=["Monitors"])


@router.get(
    "/",
    response_model=List[MonitorResponse],
    summary="Get all monitors for current user",
    description="Returns a list of all monitoring URLs for the authenticated user.",
)
async def get_monitors(user: CurrentUser, session: DBSession, redis: RedisClient):
    service = MonitorService(session, redis)
    return await service.get_all_by_user(user.id)


@router.post(
    "/add-urls",
    response_model=List[MonitorResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add URLs to monitor",
    description="Add one or more URLs to monitor. Each URL will be checked at the specified interval.",
)
async def create_monitors_bulk(
    monitors_data: List[MonitorCreate],
    user: CurrentUser,
    session: DBSession,
    redis: RedisClient,
):
    logger.info(
        "monitors_bulk_create",
        user=user.username,
        user_id=user.id,
        count=len(monitors_data),
        urls=[str(m.url) for m in monitors_data],
    )
    service = MonitorService(session, redis)
    new_monitors = await service.bulk_create_monitors(monitors_data, user_id=user.id)
    return new_monitors


@router.post(
    "/start",
    response_model=MonitoringStatus,
    summary="Start all monitoring",
    description="Activate all monitors for the current user. Worker will begin checking URLs.",
)
async def start_monitoring(user: CurrentUser, session: DBSession, redis: RedisClient):
    service = MonitorService(session, redis)
    return await service.start_all(user.id, user.username)


@router.post(
    "/stop",
    response_model=MonitoringStatus,
    summary="Stop all monitoring",
    description="Deactivate all monitors for the current user. Worker will stop checking URLs.",
)
async def stop_monitoring(user: CurrentUser, session: DBSession, redis: RedisClient):
    service = MonitorService(session, redis)
    return await service.stop_all(user.id, user.username)


@router.patch(
    "/{monitor_id}/toggle",
    response_model=MonitorResponse,
    summary="Toggle monitor active state",
    description="Toggle a specific monitor on/off.",
)
async def toggle_monitor(
    monitor_id: int, user: CurrentUser, session: DBSession, redis: RedisClient
):
    service = MonitorService(session, redis)
    monitor = await service.get_by_id(monitor_id, user.id)

    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with id={monitor_id} not found",
        )

    return await service.toggle(monitor)


@router.patch(
    "/{monitor_id}",
    response_model=MonitorResponse,
    summary="Update monitor configuration",
    description="Update monitor settings: name, URL, method, headers, body, or check interval. Redis config is automatically updated.",
)
async def update_monitor(
    monitor_id: int,
    update_data: MonitorUpdate,
    user: CurrentUser,
    session: DBSession,
    redis: RedisClient,
):
    service = MonitorService(session, redis)
    monitor = await service.get_by_id(monitor_id, user.id)

    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with id={monitor_id} not found",
        )

    updated_monitor = await service.update(monitor, update_data)

    logger.info(
        "monitor_updated_via_api",
        user=user.username,
        monitor_id=monitor_id,
        url=updated_monitor.url,
    )

    return updated_monitor


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a monitor",
    description="Remove a monitor from the system.",
)
async def delete_monitor(
    monitor_id: int, user: CurrentUser, session: DBSession, redis: RedisClient
):
    service = MonitorService(session, redis)
    monitor = await service.get_by_id(monitor_id, user.id)

    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with id={monitor_id} not found",
        )

    await service.delete(monitor)


@router.get(
    "/{monitor_id}/stats",
    response_model=List[dict],
    summary="Get monitor statistics",
    description="Get performance metrics and check history for a specific monitor.",
)
async def get_monitor_statistics(
    monitor_id: int,
    user: CurrentUser,
    session: DBSession,
    redis: RedisClient,
    hours: int = 24,
):
    service = MonitorService(session, redis)

    monitor = await service.get_by_id(monitor_id, user.id)
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with id={monitor_id} not found",
        )

    stats = await service.get_statistics(monitor_id, user.id, hours)
    return stats
