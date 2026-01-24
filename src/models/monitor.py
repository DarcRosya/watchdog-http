from typing import TYPE_CHECKING
from sqlalchemy import Index, String, Text, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from src.core.database import Base
from src.core.db_types import intpk, aware_datetime

if TYPE_CHECKING:
    from .user import User

class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        Index("scheduler_index", "is_active", "next_check_at"),
    )

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    
    name: Mapped[str] = mapped_column(String(50), nullable=True)
    url: Mapped[Text] = mapped_column(nullable=False)  

    method: Mapped[str] = mapped_column(String(10), default="GET")
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    body: Mapped[Text] = mapped_column(nullable=True)

    interval: Mapped[int] = mapped_column(nullable=False, default=60) # in seconds 
    is_active: Mapped[bool] = mapped_column(default=True)

    next_check_at: Mapped[aware_datetime]

    last_check_status: Mapped[bool] = mapped_column(nullable=True)

    created_at: mapped_column[aware_datetime] = mapped_column(server_default=func.now())
