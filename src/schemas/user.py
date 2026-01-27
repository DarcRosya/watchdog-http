from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict
from coolname import generate_slug

def generate_random_username() -> str:
    return generate_slug(2)

class UserCreate(BaseModel):
    # username generated automatically when registered
    username: str = Field(
        default_factory=generate_random_username, 
        min_length=3,
        max_length=100,
        description="The unique username of the user.",
        examples=["glossy-zebra", "lavender-wolf"]
    )
    telegram_chat_id: Optional[int] = Field(
        default=None,
        description="Telegram Chat ID for notifications.",
        examples=[123456789]
    )

class UserResponse(BaseModel):
    # 'from_attributes=True' allows creating models from ORM objects (SQLAlchemy, etc.)
    model_config = ConfigDict(from_attributes=True)
    
    id: int = Field(description="Unique identifier of the user.")
    username: str = Field(description="The username.")
    telegram_chat_id: Optional[int] = Field(
        default=None, 
        description="Telegram Chat ID."
    )
    created_at: datetime = Field(description="Creation timestamp.")

class UserUpdate(BaseModel):
    username: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=100,
        description="New username to update."
    )
    telegram_chat_id: Optional[int] = Field(
        default=None,
        description="New Telegram Chat ID to update."
    )