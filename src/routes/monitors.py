from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from src.core.database import DBSession
from src.core.dependencies import CurrentUser
from src.models.monitor import Monitor
from src.schemas.monitor import MonitorCreate, MonitorResponse, MonitoringStatus
from src.services.monitor import MonitorService

router = APIRouter(prefix="/monitors", tags=["Monitors"])


@router.get(
    "/",
    response_model=List[MonitorResponse],
    summary="Get all monitors for current user",
    description="Returns a list of all monitoring URLs for the authenticated user."
)
async def get_monitors(
    user: CurrentUser,
    session: DBSession
):
    query = select(Monitor).where(Monitor.user_id == user.id)
    result = await session.execute(query)
    monitors = result.scalars().all()
    
    return monitors


@router.post(
    "/add-urls", 
    response_model=List[MonitorResponse], 
    status_code=status.HTTP_201_CREATED,
    summary="Add URLs to monitor",
    description="Add one or more URLs to monitor. Each URL will be checked at the specified interval."
)
async def create_monitors_bulk(
    monitors_data: List[MonitorCreate], 
    user: CurrentUser,
    session: DBSession
):
    service = MonitorService(session)
    new_monitors = await service.bulk_create_monitors(monitors_data, user_id=user.id)
    return new_monitors


@router.post(
    "/start",
    response_model=MonitoringStatus,
    summary="Start all monitoring",
    description="Activate all monitors for the current user. Worker will begin checking URLs."
)
async def start_monitoring(
    user: CurrentUser,
    session: DBSession
):
    query = (
        update(Monitor)
        .where(Monitor.user_id == user.id)
        .values(is_active=True)
    )
    result = await session.execute(query)
    await session.commit()
    
    print(f"▶️ User {user.username} started monitoring ({result.rowcount} monitors)")
    
    return MonitoringStatus(
        status="started",
        message=f"Activated {result.rowcount} monitor(s)",
        affected_count=result.rowcount
    )


@router.post(
    "/stop",
    response_model=MonitoringStatus,
    summary="Stop all monitoring",
    description="Deactivate all monitors for the current user. Worker will stop checking URLs."
)
async def stop_monitoring(
    user: CurrentUser,
    session: DBSession
):
    query = (
        update(Monitor)
        .where(Monitor.user_id == user.id)
        .values(is_active=False)
    )
    result = await session.execute(query)
    await session.commit()
    
    print(f"⏹️ User {user.username} stopped monitoring ({result.rowcount} monitors)")
    
    return MonitoringStatus(
        status="stopped",
        message=f"Deactivated {result.rowcount} monitor(s)",
        affected_count=result.rowcount
    )


@router.patch(
    "/{monitor_id}/toggle",
    response_model=MonitorResponse,
    summary="Toggle monitor active state",
    description="Toggle a specific monitor on/off."
)
async def toggle_monitor(
    monitor_id: int,
    user: CurrentUser,
    session: DBSession
):
    query = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == user.id
    )
    result = await session.execute(query)
    monitor = result.scalars().first()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with id={monitor_id} not found"
        )
    
    monitor.is_active = not monitor.is_active
    await session.commit()
    await session.refresh(monitor)
    
    state = "activated" if monitor.is_active else "deactivated"
    print(f"🔄 Monitor {monitor_id} ({monitor.url}) {state}")
    
    return monitor


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a monitor",
    description="Remove a monitor from the system."
)
async def delete_monitor(
    monitor_id: int,
    user: CurrentUser,
    session: DBSession
):
    query = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == user.id
    )
    result = await session.execute(query)
    monitor = result.scalars().first()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with id={monitor_id} not found"
        )
    
    await session.delete(monitor)
    await session.commit()
    
    print(f"🗑️ Monitor {monitor_id} ({monitor.url}) deleted")