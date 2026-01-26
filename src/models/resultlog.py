from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.db_types import aware_datetime

class ResultLog(Base):
    __tablename__ = "result_logs"

    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    start_time: Mapped[aware_datetime] = mapped_column(primary_key=True)

    duration_ms: Mapped[int] = mapped_column(nullable=False)  

    status_code: Mapped[int] = mapped_column(nullable=True)
    is_success: Mapped[bool] = mapped_column(nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
