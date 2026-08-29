from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.event import TERMINAL_EVENTS, AgentEvent
from app.models.task import Task, TaskStatus, VerificationSummary

FORMAT_VERSION = 1
MAX_SESSION_TASKS = 100
MAX_RECAP_PROMPT_CHARACTERS = 4_000
MAX_RECAP_RESULT_CHARACTERS = 8_000


def _uuid_text(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("identifier must be a UUID") from exc


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskRecap(StrictModel):
    """Bounded Phase-0 contract; deterministic construction is added in Phase 4."""

    task_id: str
    ordinal: int = Field(ge=1, le=MAX_SESSION_TASKS)
    status: Literal["COMPLETED", "FAILED"]
    user_prompt: str = Field(min_length=1, max_length=MAX_RECAP_PROMPT_CHARACTERS)
    assistant_result: str | None = Field(default=None, max_length=MAX_RECAP_RESULT_CHARACTERS)
    error_code: str | None = Field(default=None, max_length=128)
    files_changed: list[str] = Field(default_factory=list, max_length=128)
    verification: VerificationSummary | None = None

    _task_uuid = field_validator("task_id")(_uuid_text)

    @field_validator("files_changed")
    @classmethod
    def validate_files_changed(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 1000 for value in values):
            raise ValueError("recap paths must be non-empty and bounded")
        if len(values) != len(set(values)):
            raise ValueError("recap paths must be unique")
        return values

    @model_validator(mode="after")
    def validate_terminal_fact(self) -> TaskRecap:
        if self.status == "COMPLETED":
            if self.assistant_result is None or self.error_code is not None:
                raise ValueError("completed recap requires a result and no error")
        elif self.assistant_result is not None or self.error_code is None:
            raise ValueError("failed recap requires an error and no assistant result")
        return self


class CommandTraceData(StrictModel):
    command: str = Field(max_length=4000)
    ok: bool
    exit_code: int | None = None
    timed_out: bool = False
    cleanup_ok: bool = True
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    stdout: str = Field(default="", max_length=2000)
    stderr: str = Field(default="", max_length=2000)
    output_truncated: bool = False


class ExecutionTraceData(StrictModel):
    files_read: list[str] = Field(default_factory=list, max_length=128)
    files_changed: list[str] = Field(default_factory=list, max_length=128)
    commands: list[CommandTraceData] = Field(default_factory=list, max_length=64)
    error_codes: list[str] = Field(default_factory=list, max_length=64)
    tool_calls: int = Field(default=0, ge=0)
    decision_steps: int = Field(default=0, ge=0)
    tool_call_ids: list[str] = Field(default_factory=list, max_length=512)

    @field_validator("files_read", "files_changed")
    @classmethod
    def validate_paths(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 1000 for value in values):
            raise ValueError("trace paths must be non-empty and bounded")
        if len(values) != len(set(values)):
            raise ValueError("trace paths must be unique")
        return values

    @field_validator("error_codes", "tool_call_ids")
    @classmethod
    def validate_short_values(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("trace values must be non-empty and bounded")
        if len(values) != len(set(values)):
            raise ValueError("trace values must be unique")
        return values


class PersistedTaskData(StrictModel):
    session_id: str
    ordinal: int = Field(ge=1, le=MAX_SESSION_TASKS)
    task: Task
    trace: ExecutionTraceData = Field(default_factory=ExecutionTraceData)
    events: list[AgentEvent] = Field(default_factory=list, max_length=512)
    first_event_id: int = Field(default=1, ge=1)
    last_event_id: int = Field(default=0, ge=0)

    _session_uuid = field_validator("session_id")(_uuid_text)

    @model_validator(mode="after")
    def validate_event_window(self) -> PersistedTaskData:
        _uuid_text(self.task.id)
        ids = [int(event.id) for event in self.events]
        if any(event.task_id != self.task.id for event in self.events):
            raise ValueError("persisted event belongs to another task")
        if ids != list(range(self.first_event_id, self.last_event_id + 1)):
            raise ValueError("persisted event IDs must be contiguous and increasing")
        if ids:
            if self.first_event_id != ids[0] or self.last_event_id != ids[-1]:
                raise ValueError("persisted event bounds do not match events")
        elif self.first_event_id != self.last_event_id + 1:
            raise ValueError("empty event window bounds are invalid")
        terminal = self.task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}
        if terminal and (self.task.finished_at is None or self.task.summary is None):
            raise ValueError("terminal task must include finished_at and summary")
        if not terminal and (self.task.finished_at is not None or self.task.summary is not None):
            raise ValueError("non-terminal task cannot include terminal fields")
        if self.task.status is TaskStatus.PENDING and self.task.started_at is not None:
            raise ValueError("pending task cannot include started_at")
        if self.task.status is TaskStatus.RUNNING and self.task.started_at is None:
            raise ValueError("running task must include started_at")
        if self.task.status is TaskStatus.COMPLETED and self.task.error is not None:
            raise ValueError("completed task cannot include an error")
        if self.task.status is TaskStatus.FAILED and (
            self.task.error is None or self.task.result is not None
        ):
            raise ValueError("failed task requires an error and no result")
        terminal_events = [event for event in self.events if event.type in TERMINAL_EVENTS]
        if len(terminal_events) > 1:
            raise ValueError("task may contain only one terminal event")
        if terminal and (not terminal_events or terminal_events[-1] != self.events[-1]):
            raise ValueError("terminal task must end with a terminal event")
        if not terminal and terminal_events:
            raise ValueError("non-terminal task cannot contain a terminal event")
        if terminal:
            expected_type = (
                "task_completed" if self.task.status is TaskStatus.COMPLETED else "task_failed"
            )
            if self.events[-1].type != expected_type:
                raise ValueError("terminal event does not match task status")
            expected_payload = (
                {"result": self.task.result}
                if self.task.status is TaskStatus.COMPLETED
                else {"error": self.task.error.model_dump()}
            )
            terminal_payload = self.events[-1].payload
            if terminal_payload != expected_payload and not (
                terminal_payload.get("payload_truncated") is True
                and isinstance(terminal_payload.get("original_characters"), int)
            ):
                raise ValueError("terminal event payload does not match task state")
        return self


class TaskEnvelope(StrictModel):
    format_version: Literal[1] = FORMAT_VERSION
    kind: Literal["task"] = "task"
    revision: int = Field(ge=1)
    data: PersistedTaskData


class SessionData(StrictModel):
    id: str
    title: str = Field(min_length=1, max_length=160)
    created_at: datetime
    updated_at: datetime
    task_ids: list[str] = Field(default_factory=list, max_length=MAX_SESSION_TASKS)
    task_count: int = Field(ge=0, le=MAX_SESSION_TASKS)
    last_task_id: str | None = None
    last_task_status: TaskStatus | None = None
    history_incomplete: bool = False

    _id_uuid = field_validator("id")(_uuid_text)

    @field_validator("task_ids")
    @classmethod
    def validate_task_ids(cls, values: list[str]) -> list[str]:
        normalized = [_uuid_text(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("session task IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_projection(self) -> SessionData:
        if self.title != " ".join(self.title.split()):
            raise ValueError("session title must be normalized to one line")
        if self.task_count != len(self.task_ids):
            raise ValueError("session task_count does not match task IDs")
        expected = self.task_ids[-1] if self.task_ids else None
        if self.last_task_id != expected:
            raise ValueError("session last_task_id does not match task IDs")
        return self


class SessionEnvelope(StrictModel):
    format_version: Literal[1] = FORMAT_VERSION
    kind: Literal["session"] = "session"
    revision: int = Field(ge=1)
    data: SessionData


class SessionIndexData(StrictModel):
    sessions: list[SessionData] = Field(default_factory=list, max_length=200)


class SessionIndexEnvelope(StrictModel):
    format_version: Literal[1] = FORMAT_VERSION
    kind: Literal["index"] = "index"
    revision: int = Field(ge=1)
    data: SessionIndexData


class WorkspaceData(StrictModel):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class WorkspaceEnvelope(StrictModel):
    format_version: Literal[1] = FORMAT_VERSION
    kind: Literal["workspace"] = "workspace"
    revision: int = Field(ge=1)
    data: WorkspaceData


class FormatData(StrictModel):
    created_at: datetime
    application_version: str = Field(min_length=1, max_length=64)


class FormatEnvelope(StrictModel):
    format_version: Literal[1] = FORMAT_VERSION
    kind: Literal["format"] = "format"
    revision: int = Field(ge=1)
    data: FormatData


class QuarantineData(StrictModel):
    source_name: str = Field(min_length=1, max_length=255)
    error_code: str = Field(min_length=1, max_length=128)
    quarantined_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class QuarantineEnvelope(StrictModel):
    format_version: Literal[1] = FORMAT_VERSION
    kind: Literal["quarantine"] = "quarantine"
    revision: int = 1
    data: QuarantineData
