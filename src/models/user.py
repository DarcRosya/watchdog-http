from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.db_types import intpk, str_100, str_150, aware_datetime

class User(Base):
    __tablename__ = "users"

    id: Mapped[intpk]
    
    username: Mapped[str_100] = mapped_column(nullable=False)
    email: Mapped[str_150] = mapped_column(unique=True, index=True, nullable=True)  
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=True)

    created_at: Mapped[aware_datetime] = mapped_column(server_default=func.now())
