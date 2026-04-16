from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.db_types import aware_datetime, intpk

if TYPE_CHECKING:
    from .user import User  # type: ignore # noqa: F401


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(50), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    method: Mapped[str] = mapped_column(String(10), default="GET")
    headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=True)

    interval: Mapped[int] = mapped_column(nullable=False, default=60)  # in seconds
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[aware_datetime] = mapped_column(server_default=func.now())
