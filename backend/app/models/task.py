from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=8000)

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value.strip()


class TaskError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str


class CommandSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(max_length=4000)
    ok: bool
    exit_code: int | None = None
    timed_out: bool = False
    cleanup_ok: bool = True
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=128)


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["pytest"] = "pytest"
    command: str = Field(max_length=4000)
    passed: bool
    exit_code: int | None = None
    output_excerpt: str | None = Field(default=None, max_length=2000)
    output_truncated: bool = False


class TaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files_read: list[str] = Field(default_factory=list, max_length=128)
    files_changed: list[str] = Field(default_factory=list, max_length=128)
    commands: list[CommandSummary] = Field(default_factory=list, max_length=64)
    verification: VerificationSummary | None = None
    tool_calls: int = Field(default=0, ge=0)
    decision_steps: int = Field(default=0, ge=0)
    error_codes: list[str] = Field(default_factory=list, max_length=64)
    duration_ms: float | None = Field(default=None, ge=0)


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()))
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: str | None = None
    error: TaskError | None = None
    mode: str = "scaffold"
    summary: TaskSummary | None = None
