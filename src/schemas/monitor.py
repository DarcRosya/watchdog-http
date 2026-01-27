from typing import Optional

from pydantic import BaseModel, HttpUrl, Field, field_validator


class MonitorCreate(BaseModel):
    url: HttpUrl 
    name: Optional[str] = None
    
    # ge=60 — greater or equal 60
    interval: int = Field(
        default=60, 
        ge=60,
        description="Check interval in seconds. Minimum 60, multiples of 60.",
        examples=[60, 120, 300, 600]
    )
    method: str = Field(
        default="GET",
        description="HTTP request method",
        examples=["GET", "POST", "HEAD"]
    )
    
    @field_validator("interval")
    @classmethod
    def interval_must_be_multiple_of_60(cls, v: int) -> int:
        if v % 60 != 0:
            raise ValueError(
                f"The interval must be a multiple of 60 seconds (whole minutes). "
                f"Received: {v}. Try: {(v // 60 + 1) * 60}"
            )
        return v


class MonitorResponse(MonitorCreate):
    id: int
    is_active: bool