from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    mode: Literal["demo"]
    time: int = Field(ge=0, description="Unix epoch milliseconds in UTC; event occurrence.")
    updated: int = Field(ge=0, description="Unix epoch milliseconds in UTC; source version.")
    ingested_at: datetime = Field(description="UTC timestamp when the system received the message.")
    replayed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when replayed; null for this delivery.",
    )
    payload: dict[str, Any]
    synthetic_flag: bool

    @field_validator("ingested_at", "replayed_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("timestamps must use UTC")
        return value
