from sqlalchemy import BigInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.db_types import intpk, aware_datetime

class User(Base):
    __tablename__ = "users"

    id: Mapped[intpk]
    
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=True)

    created_at: Mapped[aware_datetime] = mapped_column(server_default=func.now())
