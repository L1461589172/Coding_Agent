from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.task import utc_now

EventType = Literal[
    "task_started",
    "assistant_message",
    "tool_started",
    "tool_finished",
    "file_changed",
    "command_finished",
    "task_completed",
    "task_failed",
]
TERMINAL_EVENTS = {"task_completed", "task_failed"}


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Task-local, increasing SSE cursor. Unique together with task_id.
    id: str
    task_id: str
    type: EventType
    timestamp: datetime = Field(default_factory=utc_now)
    step: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.isascii() or not value.isdigit() or int(value) < 1 or str(int(value)) != value:
            raise ValueError("event id must be a canonical positive integer")
        return value

    def as_sse(self) -> str:
        # A single JSON line; message text cannot inject SSE fields.
        return f"id: {self.id}\ndata: {self.model_dump_json()}\n\n"
