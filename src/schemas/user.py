from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class UserResponse(BaseModel):
    # 'from_attributes=True' allows creating models from ORM objects (SQLAlchemy, etc.)
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Unique identifier of the user.")
    username: str = Field(description="The username.")
    api_key: str = Field(description="API key for authentication.")
    telegram_chat_id: int | None = Field(default=None, description="Telegram Chat ID.")
    created_at: datetime = Field(description="Creation timestamp.")


class UserUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
        description="New username to update.",
    )
    telegram_chat_id: int | None = Field(
        default=None, description="New Telegram Chat ID to update."
    )
