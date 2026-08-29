import shlex
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.events import EventLog
from app.models.event import AgentEvent, EventType
from app.models.task import (
    CommandSummary,
    Task,
    TaskSummary,
    VerificationSummary,
)

MAX_FILES = 128
MAX_COMMANDS = 64
MAX_ERRORS = 64
MAX_PATH_CHARACTERS = 1000
MAX_COMMAND_CHARACTERS = 4000
MAX_EXCERPT_CHARACTERS = 2000


def _bounded(value: Any, limit: int) -> str:
    return str(value)[:limit]


def _append_unique(items: list[str], value: Any, *, limit: int, characters: int) -> None:
    if value is None or len(items) >= limit:
        return
    bounded = _bounded(value, characters)
    if bounded and bounded not in items:
        items.append(bounded)


def _pytest_command(command: str) -> bool:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not argv:
        return False
    executable = argv[0].casefold()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable == "pytest":
        return True
    return executable in {"python", "python3"} and len(argv) >= 3 and argv[1:3] == ["-m", "pytest"]


@dataclass
class CommandTrace:
    command: str
    ok: bool
    exit_code: int | None
    timed_out: bool
    cleanup_ok: bool
    duration_ms: float | None
    error_code: str | None
    stdout: str
    stderr: str
    output_truncated: bool


@dataclass
class ExecutionTrace:
    files_read: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands: list[CommandTrace] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    tool_calls: int = 0
    decision_steps: int = 0
    _tool_call_ids: set[str] = field(default_factory=set, repr=False)

    def observe(self, kind: EventType, payload: dict[str, Any]) -> None:
        if kind == "assistant_message" and payload.get("mode") == "agent":
            self.decision_steps += 1
            return
        if kind == "tool_started":
            call_id = payload.get("call_id")
            if isinstance(call_id, str) and call_id not in self._tool_call_ids:
                self._tool_call_ids.add(call_id)
                self.tool_calls += 1
            return
        if kind == "tool_finished":
            error_code = payload.get("error_code")
            if error_code:
                _append_unique(
                    self.error_codes,
                    error_code,
                    limit=MAX_ERRORS,
                    characters=128,
                )
            if payload.get("tool") == "read_file" and payload.get("ok") is True:
                result = payload.get("result")
                output = result.get("output") if isinstance(result, dict) else None
                if isinstance(output, dict):
                    _append_unique(
                        self.files_read,
                        output.get("path"),
                        limit=MAX_FILES,
                        characters=MAX_PATH_CHARACTERS,
                    )
            return
        if kind == "file_changed":
            _append_unique(
                self.files_changed,
                payload.get("path"),
                limit=MAX_FILES,
                characters=MAX_PATH_CHARACTERS,
            )
            return
        if kind == "command_finished" and len(self.commands) < MAX_COMMANDS:
            stdout = _bounded(payload.get("stdout") or "", MAX_EXCERPT_CHARACTERS)
            stderr = _bounded(payload.get("stderr") or "", MAX_EXCERPT_CHARACTERS)
            error_code = payload.get("error_code")
            self.commands.append(
                CommandTrace(
                    command=_bounded(payload.get("command") or "", MAX_COMMAND_CHARACTERS),
                    ok=payload.get("ok") is True,
                    exit_code=(
                        payload.get("exit_code")
                        if isinstance(payload.get("exit_code"), int)
                        else None
                    ),
                    timed_out=payload.get("timed_out") is True,
                    cleanup_ok=payload.get("cleanup_ok") is not False,
                    duration_ms=(
                        float(payload["duration_ms"])
                        if isinstance(payload.get("duration_ms"), int | float)
                        else None
                    ),
                    error_code=_bounded(error_code, 128) if error_code else None,
                    stdout=stdout,
                    stderr=stderr,
                    output_truncated=(
                        payload.get("stdout_truncated") is True
                        or payload.get("stderr_truncated") is True
                        or len(str(payload.get("stdout") or "")) > len(stdout)
                        or len(str(payload.get("stderr") or "")) > len(stderr)
                    ),
                )
            )
            if error_code:
                _append_unique(
                    self.error_codes,
                    error_code,
                    limit=MAX_ERRORS,
                    characters=128,
                )


class TraceRecorder:
    def __init__(
        self,
        events: EventLog,
        trace: ExecutionTrace,
        commit: Callable[[AgentEvent, ExecutionTrace], Awaitable[None]] | None = None,
    ) -> None:
        self.events = events
        self.trace = trace
        self.commit = commit

    async def publish(
        self,
        task_id: str,
        kind: EventType,
        payload: dict[str, Any],
        step: int = 0,
    ) -> AgentEvent:
        next_trace = deepcopy(self.trace)
        next_trace.observe(kind, payload)

        async def before_notify(event: AgentEvent) -> None:
            if self.commit is not None:
                await self.commit(event, next_trace)

        event = await self.events.publish(
            task_id,
            kind,
            payload,
            step,
            before_notify=before_notify if self.commit is not None else None,
        )
        self.trace.files_read = next_trace.files_read
        self.trace.files_changed = next_trace.files_changed
        self.trace.commands = next_trace.commands
        self.trace.error_codes = next_trace.error_codes
        self.trace.tool_calls = next_trace.tool_calls
        self.trace.decision_steps = next_trace.decision_steps
        self.trace._tool_call_ids = next_trace._tool_call_ids
        return event


def build_task_summary(task: Task, trace: ExecutionTrace) -> TaskSummary:
    commands = [
        CommandSummary(
            command=command.command,
            ok=command.ok,
            exit_code=command.exit_code,
            timed_out=command.timed_out,
            cleanup_ok=command.cleanup_ok,
            duration_ms=command.duration_ms,
            error_code=command.error_code,
        )
        for command in trace.commands
    ]
    verification = None
    for command in trace.commands:
        if not _pytest_command(command.command):
            continue
        excerpt = "\n".join(part for part in (command.stdout, command.stderr) if part).strip()
        verification = VerificationSummary(
            command=command.command,
            passed=command.ok and command.exit_code == 0 and not command.timed_out,
            exit_code=command.exit_code,
            output_excerpt=excerpt[:MAX_EXCERPT_CHARACTERS] or None,
            output_truncated=command.output_truncated,
        )

    errors = list(trace.error_codes)
    if task.error is not None:
        _append_unique(errors, task.error.code, limit=MAX_ERRORS, characters=128)
    duration_ms = _duration_ms(task.started_at, task.finished_at)
    return TaskSummary(
        files_read=list(trace.files_read),
        files_changed=list(trace.files_changed),
        commands=commands,
        verification=verification,
        tool_calls=trace.tool_calls,
        decision_steps=trace.decision_steps,
        error_codes=errors,
        duration_ms=duration_ms,
    )


def _duration_ms(started: datetime | None, finished: datetime | None) -> float | None:
    if started is None or finished is None:
        return None
    return max(0.0, round((finished - started).total_seconds() * 1000, 3))
