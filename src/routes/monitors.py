from typing import List

from fastapi import APIRouter, status

from src.core.database import DBSession
from src.schemas.monitor import MonitorCreate, MonitorResponse
from src.services.monitor import MonitorService

router = APIRouter(prefix="/monitors", tags=["Monitors"])

@router.post(
    "/add-urls", 
    response_model=List[MonitorResponse], 
    status_code=status.HTTP_201_CREATED
)
async def create_monitors_bulk(
    monitors_data: List[MonitorCreate], 
    session: DBSession
):
    service = MonitorService(session)
    # user_id пока хардкодим
    new_monitors = await service.bulk_create_monitors(monitors_data, user_id=1)
    return new_monitors