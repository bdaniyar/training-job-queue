import base64
import binascii
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

State = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    duration_ms: int = Field(default=100, ge=0, le=60_000)
    value: int = Field(default=1, ge=-1_000_000, le=1_000_000)
    fail_attempts: int = Field(default=0, ge=0, le=4)
    fail_permanently: bool = False


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payload: Payload
    state: State
    attempts: int
    generation: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    result: dict | None
    error: str | None


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_at: Annotated[datetime, Field()]
    id: UUID

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()

    @classmethod
    def decode(cls, value: str) -> "Cursor":
        try:
            decoded = base64.b64decode(value, altchars=b"-_", validate=True)
            cursor = cls.model_validate(json.loads(decoded))
            if cursor.created_at.tzinfo is None:
                raise ValueError("cursor timestamp must contain timezone")
            return cursor
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid pagination cursor") from exc


class JobPage(BaseModel):
    items: list[JobOut]
    next_cursor: str | None
