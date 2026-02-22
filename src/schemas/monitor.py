from typing import Annotated, Optional
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    HttpUrl,
    Field,
    StringConstraints,
    field_validator,
)


class HttpMethod(str, Enum):
    """Allowed HTTP methods for monitor requests."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class MonitorCreate(BaseModel):
    url: HttpUrl
    name: Optional[
        Annotated[str, StringConstraints(max_length=50, strip_whitespace=True)]
    ] = None
    headers: Optional[dict[str, str]] = Field(
        None, description="Custom HTTP headers for the probe"
    )
    body: Optional[str] = Field(
        None, description="Request body for POST/PUT/PATCH/DELETE requests"
    )

    # ge=60 — greater or equal 60
    interval: int = Field(
        default=60,
        ge=60,
        description="Check interval in seconds. Minimum 60, multiples of 60.",
        examples=[60, 120, 300, 600],
    )
    method: HttpMethod = Field(
        default=HttpMethod.GET,
        description="HTTP request method",
        examples=["GET", "POST", "HEAD"],
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
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


class MonitorUpdate(BaseModel):
    name: Optional[
        Annotated[str, StringConstraints(max_length=50, strip_whitespace=True)]
    ] = None
    url: Optional[HttpUrl] = Field(None, description="URL to monitor")
    method: Optional[HttpMethod] = Field(None, description="HTTP request method")
    headers: Optional[dict[str, str]] = Field(None, description="Custom HTTP headers")
    body: Optional[str] = Field(None, description="Request body for POST/PUT/PATCH")
    interval: Optional[int] = Field(
        None,
        ge=60,
        description="Check interval in seconds (minimum 60, multiples of 60)",
        examples=[60, 120, 300, 600],
    )

    @field_validator("interval")
    @classmethod
    def interval_must_be_multiple_of_60(cls, v: int | None) -> int | None:
        if v is not None and v % 60 != 0:
            raise ValueError(
                f"The interval must be a multiple of 60 seconds (whole minutes). "
                f"Received: {v}. Try: {(v // 60 + 1) * 60}"
            )
        return v


class MonitoringStatus(BaseModel):
    status: str = Field(description="Current status: 'started' or 'stopped'")
    message: str = Field(description="Human-readable status message")
    affected_count: int = Field(description="Number of monitors affected")
