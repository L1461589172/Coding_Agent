from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from app.core.events import EventLimits
from app.history.atomic import atomic_write_json
from app.history.errors import (
    HistoryCapacity,
    HistoryDataInvalid,
    HistoryStorageUnavailable,
    SessionNotFound,
    SessionTaskLimit,
)
from app.history.lock import HistoryFileLock
from app.history.migrations import initialize_or_migrate
from app.history.models import (
    CommandTraceData,
    ExecutionTraceData,
    PersistedTaskData,
    QuarantineData,
    QuarantineEnvelope,
    SessionData,
    SessionEnvelope,
    SessionIndexData,
    SessionIndexEnvelope,
    TaskEnvelope,
    WorkspaceData,
    WorkspaceEnvelope,
)
from app.history.paths import (
    HistoryPaths,
    ensure_history_root,
    ensure_real_directory,
    path_is_link,
    validated_uuid,
)
from app.models.event import AgentEvent
from app.models.task import Task, TaskError, TaskStatus, utc_now
from app.services.trace import CommandTrace, ExecutionTrace, build_task_summary


class HistoryRepository(Protocol):
    async def create_with_task(
        self, task: Task, trace: ExecutionTrace, session_id: str | None = None
    ) -> PersistedTaskData: ...

    def get_task(self, task_id: str) -> Task: ...

    def get_persisted_task(self, task_id: str) -> PersistedTaskData: ...

    def has_unfinished_task(self) -> bool: ...

    def get_session(self, session_id: str) -> SessionData: ...

    def list_sessions(
        self, limit: int, before: str | None = None
    ) -> tuple[list[SessionData], str | None]: ...

    def list_session_tasks(
        self, session_id: str, limit: int, before_ordinal: int | None = None
    ) -> tuple[list[PersistedTaskData], int | None]: ...

    async def commit_task_event(
        self, task: Task, event: AgentEvent, trace: ExecutionTrace
    ) -> None: ...

    async def reconcile_interrupted(self) -> list[str]: ...

    async def delete_session(self, session_id: str) -> None: ...

    async def close(self) -> None: ...


_SESSION_TITLE_MAX_CHARACTERS = 80


def _title_line(value: str) -> str:
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if not line or line.startswith("```"):
            continue
        line = line.strip("#>*_`- ").replace("`", "").strip()
        if line:
            return line[:_SESSION_TITLE_MAX_CHARACTERS].rstrip("：:。.!！,，;； ")
    return ""


def _prompt_title(prompt: str) -> str:
    return _title_line(prompt) or "未命名会话"


def _session_title(first_task: Task) -> str:
    if first_task.status is TaskStatus.COMPLETED and first_task.result:
        summary = _title_line(first_task.result)
        if summary:
            return summary
    return _prompt_title(first_task.prompt)


def _session_cursor(updated_at: datetime, session_id: str) -> str:
    raw = json.dumps(
        [updated_at.astimezone(UTC).isoformat(), validated_uuid(session_id)],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_session_cursor(value: str) -> tuple[datetime, str]:
    if not value or len(value) > 256 or not value.isascii():
        raise HistoryDataInvalid("Session cursor is invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        decoded = json.loads(raw.decode("ascii"))
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError
        updated_at = datetime.fromisoformat(decoded[0])
        if updated_at.tzinfo is None:
            raise ValueError
        session_id = validated_uuid(decoded[1])
    except (ValueError, TypeError, UnicodeError, binascii.Error, HistoryStorageUnavailable) as exc:
        raise HistoryDataInvalid("Session cursor is invalid") from exc
    normalized = updated_at.astimezone(UTC)
    if _session_cursor(normalized, session_id) != value:
        raise HistoryDataInvalid("Session cursor is not canonical")
    return normalized, session_id


_Envelope = TypeVar("_Envelope", bound=BaseModel)
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_TASK_QUARANTINES_PER_START = 10


def _read_envelope(path: Path, model: type[_Envelope]) -> _Envelope:
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise HistoryDataInvalid("History JSON exceeds the format limit")
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HistoryStorageUnavailable("History JSON could not be read") from exc
    try:
        return model.model_validate_json(value)
    except ValueError as exc:
        raise HistoryDataInvalid("History JSON is invalid") from exc


def _trace_data(trace: ExecutionTrace) -> ExecutionTraceData:
    return ExecutionTraceData(
        files_read=list(trace.files_read),
        files_changed=list(trace.files_changed),
        commands=[
            CommandTraceData(
                command=command.command,
                ok=command.ok,
                exit_code=command.exit_code,
                timed_out=command.timed_out,
                cleanup_ok=command.cleanup_ok,
                duration_ms=command.duration_ms,
                error_code=command.error_code,
                stdout=command.stdout,
                stderr=command.stderr,
                output_truncated=command.output_truncated,
            )
            for command in trace.commands
        ],
        error_codes=list(trace.error_codes),
        tool_calls=trace.tool_calls,
        decision_steps=trace.decision_steps,
        tool_call_ids=sorted(trace._tool_call_ids),
    )


def trace_from_data(value: ExecutionTraceData) -> ExecutionTrace:
    return ExecutionTrace(
        files_read=list(value.files_read),
        files_changed=list(value.files_changed),
        commands=[
            CommandTrace(
                command=command.command,
                ok=command.ok,
                exit_code=command.exit_code,
                timed_out=command.timed_out,
                cleanup_ok=command.cleanup_ok,
                duration_ms=command.duration_ms,
                error_code=command.error_code,
                stdout=command.stdout,
                stderr=command.stderr,
                output_truncated=command.output_truncated,
            )
            for command in value.commands
        ],
        error_codes=list(value.error_codes),
        tool_calls=value.tool_calls,
        decision_steps=value.decision_steps,
        _tool_call_ids=set(value.tool_call_ids),
    )


def _append_event(
    current: PersistedTaskData,
    task: Task,
    event: AgentEvent,
    trace: ExecutionTrace,
    limits: EventLimits,
) -> PersistedTaskData:
    if event.task_id != task.id or int(event.id) != current.last_event_id + 1:
        raise HistoryDataInvalid("Task event sequence is invalid")
    events = [*current.events, event]
    characters = sum(len(item.as_sse()) for item in events)
    while len(events) > 1 and (
        len(events) > limits.max_history_events or characters > limits.max_history_characters
    ):
        characters -= len(events.pop(0).as_sse())
    return PersistedTaskData(
        session_id=current.session_id,
        ordinal=current.ordinal,
        task=task.model_copy(deep=True),
        trace=_trace_data(trace),
        events=events,
        first_event_id=int(events[0].id),
        last_event_id=int(event.id),
    )


class InMemoryHistoryRepository:
    def __init__(
        self,
        event_limits: EventLimits | None = None,
        *,
        max_sessions: int = 200,
        max_tasks_per_session: int = 100,
    ) -> None:
        self.event_limits = event_limits or EventLimits()
        self.max_sessions = max_sessions
        self.max_tasks_per_session = max_tasks_per_session
        self.tasks: dict[str, TaskEnvelope] = {}
        self.sessions: dict[str, SessionEnvelope] = {}
        self.task_sessions: dict[str, str] = {}
        self._write_lock = asyncio.Lock()

    def _new_records(
        self, task: Task, trace: ExecutionTrace
    ) -> tuple[SessionEnvelope, TaskEnvelope]:
        session_id = str(uuid4())
        task.session_id = session_id
        task.ordinal = 1
        session = SessionEnvelope(
            revision=1,
            data=SessionData(
                id=session_id,
                title=_prompt_title(task.prompt),
                created_at=task.created_at,
                updated_at=task.created_at,
                task_ids=[task.id],
                task_count=1,
                last_task_id=task.id,
                last_task_status=task.status,
            ),
        )
        persisted = TaskEnvelope(
            revision=1,
            data=PersistedTaskData(
                session_id=session_id,
                ordinal=1,
                task=task.model_copy(deep=True),
                trace=_trace_data(trace),
                events=[],
                first_event_id=1,
                last_event_id=0,
            ),
        )
        return session, persisted

    async def create_with_task(
        self, task: Task, trace: ExecutionTrace, session_id: str | None = None
    ) -> PersistedTaskData:
        async with self._write_lock:
            if task.id in self.tasks:
                raise HistoryDataInvalid("Task identifier already exists")
            if session_id is None:
                if len(self.sessions) >= self.max_sessions:
                    raise HistoryCapacity("History session limit reached")
                session, persisted = self._new_records(task, trace)
                await self._store_new(session, persisted)
            else:
                normalized = validated_uuid(session_id)
                try:
                    current = self.sessions[normalized]
                except KeyError as exc:
                    raise SessionNotFound("Session was not found") from exc
                if current.data.task_count >= self.max_tasks_per_session:
                    raise SessionTaskLimit("Session task limit reached")
                if current.data.last_task_status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                    raise HistoryDataInvalid("Session has an unfinished Task")
                ordinal = current.data.task_count + 1
                task.session_id = normalized
                task.ordinal = ordinal
                persisted = TaskEnvelope(
                    revision=1,
                    data=PersistedTaskData(
                        session_id=normalized,
                        ordinal=ordinal,
                        task=task.model_copy(deep=True),
                        trace=_trace_data(trace),
                        events=[],
                        first_event_id=1,
                        last_event_id=0,
                    ),
                )
                session = SessionEnvelope(
                    revision=current.revision + 1,
                    data=current.data.model_copy(
                        update={
                            "updated_at": task.created_at,
                            "task_ids": [*current.data.task_ids, task.id],
                            "task_count": ordinal,
                            "last_task_id": task.id,
                            "last_task_status": task.status,
                        }
                    ),
                )
                await self._store_append(session, persisted)
            self.sessions[session.data.id] = session
            self.tasks[task.id] = persisted
            self.task_sessions[task.id] = session.data.id
            return persisted.data.model_copy(deep=True)

    async def _store_new(self, session: SessionEnvelope, task: TaskEnvelope) -> None:
        del session, task

    async def _store_append(self, session: SessionEnvelope, task: TaskEnvelope) -> None:
        del session, task

    def get_task(self, task_id: str) -> Task:
        return self.tasks[task_id].data.task.model_copy(deep=True)

    def get_persisted_task(self, task_id: str) -> PersistedTaskData:
        return self.tasks[task_id].data.model_copy(deep=True)

    def has_unfinished_task(self) -> bool:
        return any(
            envelope.data.task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}
            for envelope in self.tasks.values()
        )

    def get_session(self, session_id: str) -> SessionData:
        try:
            return self.sessions[validated_uuid(session_id)].data.model_copy(deep=True)
        except (KeyError, HistoryStorageUnavailable) as exc:
            raise SessionNotFound("Session was not found") from exc

    def list_sessions(
        self, limit: int, before: str | None = None
    ) -> tuple[list[SessionData], str | None]:
        if not 1 <= limit <= 100:
            raise HistoryDataInvalid("Session page limit is invalid")
        sessions = sorted(
            (session.data for session in self.sessions.values()),
            key=lambda value: (value.updated_at, value.id),
            reverse=True,
        )
        if before is not None:
            cursor = _decode_session_cursor(before)
            sessions = [
                session
                for session in sessions
                if (session.updated_at.astimezone(UTC), session.id) < cursor
            ]
        selected = sessions[:limit]
        next_cursor = None
        if len(sessions) > limit:
            last = selected[-1]
            next_cursor = _session_cursor(last.updated_at, last.id)
        return [session.model_copy(deep=True) for session in selected], next_cursor

    def list_session_tasks(
        self, session_id: str, limit: int, before_ordinal: int | None = None
    ) -> tuple[list[PersistedTaskData], int | None]:
        if not 1 <= limit <= 100:
            raise HistoryDataInvalid("Task page limit is invalid")
        normalized = validated_uuid(session_id)
        try:
            session = self.sessions[normalized]
        except KeyError as exc:
            raise SessionNotFound("Session was not found") from exc
        tasks = sorted(
            (self.tasks[task_id].data for task_id in session.data.task_ids),
            key=lambda value: value.ordinal,
            reverse=True,
        )
        if before_ordinal is not None:
            if not 1 <= before_ordinal <= 101:
                raise HistoryDataInvalid("Task ordinal cursor is invalid")
            tasks = [task for task in tasks if task.ordinal < before_ordinal]
        selected = tasks[:limit]
        next_ordinal = selected[-1].ordinal if len(tasks) > limit else None
        return [task.model_copy(deep=True) for task in selected], next_ordinal

    async def commit_task_event(self, task: Task, event: AgentEvent, trace: ExecutionTrace) -> None:
        async with self._write_lock:
            current = self.tasks[task.id]
            updated = TaskEnvelope(
                revision=current.revision + 1,
                data=_append_event(current.data, task, event, trace, self.event_limits),
            )
            session = self.sessions[current.data.session_id]
            projection = {
                "updated_at": task.finished_at or event.timestamp,
                "last_task_status": task.status,
            }
            if current.data.ordinal == 1 and task.status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
            }:
                projection["title"] = _session_title(task)
            session_data = session.data.model_copy(update=projection)
            updated_session = SessionEnvelope(
                revision=session.revision + 1,
                data=session_data,
            )
            await self._store_update(updated, updated_session)
            self.tasks[task.id] = updated
            self.sessions[session.data.id] = updated_session

    async def _store_update(self, task: TaskEnvelope, session: SessionEnvelope) -> None:
        del task, session

    async def reconcile_interrupted(self) -> list[str]:
        reconciled: list[str] = []
        for task_id, envelope in list(self.tasks.items()):
            task = envelope.data.task.model_copy(deep=True)
            if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                continue
            trace = trace_from_data(envelope.data.trace)
            task.status = TaskStatus.FAILED
            task.finished_at = utc_now()
            task.error = TaskError(
                code="SERVER_RESTARTED",
                message="Task stopped because the service restarted",
            )
            task.result = None
            task.summary = build_task_summary(task, trace)
            event = AgentEvent(
                id=str(envelope.data.last_event_id + 1),
                task_id=task.id,
                type="task_failed",
                timestamp=task.finished_at,
                payload={"error": task.error.model_dump()},
            )
            await self.commit_task_event(task, event, trace)
            reconciled.append(task_id)
        return reconciled

    async def delete_session(self, session_id: str) -> None:
        async with self._write_lock:
            normalized = validated_uuid(session_id)
            try:
                session = self.sessions[normalized]
            except KeyError as exc:
                raise SessionNotFound("Session was not found") from exc
            await self._store_delete(session)
            for task_id in session.data.task_ids:
                self.tasks.pop(task_id, None)
                self.task_sessions.pop(task_id, None)
            self.sessions.pop(normalized, None)

    async def _store_delete(self, session: SessionEnvelope) -> None:
        del session

    async def close(self) -> None:
        return None


class JsonHistoryRepository(InMemoryHistoryRepository):
    def __init__(
        self,
        history_dir: Path,
        workspace: Path,
        event_limits: EventLimits | None = None,
        *,
        application_root: Path | None = None,
        max_sessions: int = 200,
        max_tasks_per_session: int = 100,
        backup_limit: int = 3,
        backup_max_bytes: int = 64 * 1024 * 1024,
        max_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        super().__init__(
            event_limits,
            max_sessions=max_sessions,
            max_tasks_per_session=max_tasks_per_session,
        )
        self.history_dir = history_dir
        self.workspace_root = workspace.resolve(strict=True)
        self.application_root = application_root
        self.backup_limit = backup_limit
        self.backup_max_bytes = backup_max_bytes
        self.max_bytes = max_bytes
        self.paths: HistoryPaths | None = None
        self._file_lock: HistoryFileLock | None = None
        self._opened = False
        self._index_revision = 0

    def _history_size_sync(self) -> int:
        assert self.paths is not None
        total = 0
        for root, directories, files in os.walk(self.paths.root, followlinks=False):
            root_path = Path(root)
            if path_is_link(root_path):
                raise HistoryStorageUnavailable("History storage cannot contain linked directories")
            linked_directories = [name for name in directories if path_is_link(root_path / name)]
            if linked_directories:
                raise HistoryStorageUnavailable("History storage cannot contain linked directories")
            for name in files:
                path = root_path / name
                if path_is_link(path):
                    raise HistoryStorageUnavailable("History storage cannot contain linked files")
                try:
                    total += path.stat().st_size
                except OSError as exc:
                    raise HistoryStorageUnavailable(
                        "History capacity could not be measured"
                    ) from exc
        return total

    def _ensure_replacement_capacity_sync(self, *replacements: tuple[Path, BaseModel]) -> None:
        growth = 0
        for path, value in replacements:
            encoded = value.model_dump_json().encode("utf-8")
            try:
                current = path.stat().st_size if path.is_file() else 0
            except OSError as exc:
                raise HistoryStorageUnavailable("History capacity could not be measured") from exc
            growth += max(0, len(encoded) - current)
        if self._history_size_sync() + growth > self.max_bytes:
            raise HistoryCapacity("History byte limit reached")

    def _cleanup_trash_sync(self) -> None:
        trash = self._workspace_path() / "trash"
        ensure_real_directory(trash, boundary=self.paths.root if self.paths else trash.parent)
        for batch in list(trash.iterdir()):
            if path_is_link(batch) or not batch.is_dir():
                raise HistoryStorageUnavailable("History trash contains an invalid entry")
            # Cleanup is best-effort after the authoritative index no longer exposes
            # the Session. Windows scanners can race individual unlinks.
            shutil.rmtree(batch, ignore_errors=True)

    async def open(self) -> None:
        if self._opened:
            return
        await asyncio.to_thread(self._open_sync)
        self._opened = True

    def _open_sync(self) -> None:
        root = ensure_history_root(self.history_dir, application_root=self.application_root)
        paths = HistoryPaths(root, self.workspace_root)
        if path_is_link(paths.lock):
            raise HistoryStorageUnavailable("History lock cannot be a link")
        lock = HistoryFileLock(paths.lock)
        lock.acquire()
        try:
            initialize_or_migrate(
                paths,
                backup_limit=self.backup_limit,
                backup_max_bytes=self.backup_max_bytes,
            )
            self.paths = paths
            self._load_workspace_sync()
            self._file_lock = lock
        except BaseException:
            lock.release()
            raise

    def _workspace_path(self) -> Path:
        if self.paths is None:
            raise HistoryStorageUnavailable("History repository is not open")
        return self.paths.workspace()

    def _load_workspace_sync(self) -> None:
        assert self.paths is not None
        workspace_path = self.paths.workspace()
        sessions_path = self.paths.sessions()
        ensure_real_directory(workspace_path, boundary=self.paths.root)
        ensure_real_directory(sessions_path, boundary=self.paths.root)
        ensure_real_directory(workspace_path / "trash", boundary=self.paths.root)
        workspace_file = workspace_path / "workspace.json"
        workspace: WorkspaceEnvelope | None = None
        if path_is_link(workspace_file):
            raise HistoryStorageUnavailable("Workspace history metadata cannot be a link")
        if workspace_file.exists():
            try:
                workspace = _read_envelope(workspace_file, WorkspaceEnvelope)
                if workspace.data.fingerprint != self.paths.fingerprint:
                    raise HistoryDataInvalid("Workspace fingerprint does not match its directory")
            except HistoryDataInvalid:
                self._quarantine_sync(workspace_file, "HISTORY_WORKSPACE_INVALID")
                workspace = None
        if workspace is None:
            atomic_write_json(
                workspace_file,
                WorkspaceEnvelope(
                    revision=1,
                    data=WorkspaceData(
                        fingerprint=self.paths.fingerprint,
                        created_at=datetime.now(UTC),
                    ),
                ),
            )

        index_file = workspace_path / "index.json"
        stored_index: SessionIndexEnvelope | None = None
        if path_is_link(index_file):
            raise HistoryStorageUnavailable("History index cannot be a link")
        if index_file.exists():
            try:
                stored_index = _read_envelope(index_file, SessionIndexEnvelope)
            except HistoryDataInvalid:
                self._quarantine_sync(index_file, "HISTORY_INDEX_INVALID")

        loaded_tasks: dict[str, TaskEnvelope] = {}
        loaded_sessions: dict[str, SessionEnvelope] = {}
        task_sessions: dict[str, str] = {}
        quarantined_tasks = 0
        for temporary in sessions_path.glob(".session-tmp-*"):
            if path_is_link(temporary):
                raise HistoryDataInvalid("History staging directory cannot be a link")
            if temporary.is_dir():
                shutil.rmtree(temporary)
        for session_dir in sorted(sessions_path.iterdir()):
            if path_is_link(session_dir):
                raise HistoryStorageUnavailable("History Session directory cannot be a link")
            if not session_dir.is_dir():
                continue
            try:
                session_id = validated_uuid(session_dir.name)
            except HistoryStorageUnavailable:
                continue
            stored_session: SessionEnvelope | None = None
            session_file = session_dir / "session.json"
            if path_is_link(session_file):
                raise HistoryStorageUnavailable("Session history metadata cannot be a link")
            if session_file.exists():
                try:
                    stored_session = _read_envelope(session_file, SessionEnvelope)
                    if stored_session.data.id != session_id:
                        raise HistoryDataInvalid("Session projection identifier is invalid")
                except HistoryDataInvalid:
                    self._quarantine_sync(session_file, "HISTORY_SESSION_INVALID")
                    stored_session = None
            valid: list[TaskEnvelope] = []
            incomplete = False
            tasks_dir = session_dir / "tasks"
            if path_is_link(tasks_dir):
                raise HistoryStorageUnavailable("History Task directory cannot be a link")
            if tasks_dir.is_dir():
                for task_path in sorted(tasks_dir.glob("*.json")):
                    if path_is_link(task_path):
                        raise HistoryStorageUnavailable("History Task JSON cannot be a link")
                    try:
                        envelope = _read_envelope(task_path, TaskEnvelope)
                        if envelope.data.session_id != session_id:
                            raise HistoryDataInvalid("Task session does not match its directory")
                        expected = f"{envelope.data.ordinal:010d}-{envelope.data.task.id}.json"
                        if task_path.name != expected or envelope.data.task.id in loaded_tasks:
                            raise HistoryDataInvalid("Task path or identifier is invalid")
                        valid.append(envelope)
                    except HistoryDataInvalid:
                        incomplete = True
                        self._quarantine_sync(task_path, "HISTORY_TASK_INVALID")
                        quarantined_tasks += 1
                        if quarantined_tasks > _MAX_TASK_QUARANTINES_PER_START:
                            raise HistoryDataInvalid(
                                "Too many Task history files are invalid; startup was stopped"
                            ) from None
            if not valid:
                continue
            valid.sort(key=lambda value: value.data.ordinal)
            ordinals = [value.data.ordinal for value in valid]
            if ordinals != sorted(set(ordinals)):
                raise HistoryDataInvalid("Session contains duplicate task ordinals")
            if ordinals != list(range(1, ordinals[-1] + 1)):
                incomplete = True
            incomplete = incomplete or bool(
                stored_session and stored_session.data.history_incomplete
            )
            rebuilt = self._rebuilt_session(
                session_id,
                valid,
                incomplete,
                revision=(stored_session.revision + 1 if stored_session else 1),
            )
            if stored_session is not None and stored_session.data == rebuilt.data:
                session = stored_session
            else:
                session = rebuilt
                atomic_write_json(session_file, session)
            loaded_sessions[session_id] = session
            for envelope in valid:
                task_id = envelope.data.task.id
                loaded_tasks[task_id] = envelope
                task_sessions[task_id] = session_id

        if len(loaded_sessions) > self.max_sessions:
            raise HistoryCapacity("History session limit is lower than stored history")
        self.tasks = loaded_tasks
        self.sessions = loaded_sessions
        self.task_sessions = task_sessions
        self._write_index_sync(stored_index)
        self._cleanup_trash_sync()

    def _rebuilt_session(
        self,
        session_id: str,
        tasks: list[TaskEnvelope],
        incomplete: bool,
        *,
        revision: int,
    ) -> SessionEnvelope:
        first = tasks[0].data.task
        last = tasks[-1].data.task
        updated = max(
            [
                task.data.task.finished_at or task.data.task.started_at or task.data.task.created_at
                for task in tasks
            ]
            + [event.timestamp for task in tasks for event in task.data.events]
        )
        return SessionEnvelope(
            revision=revision,
            data=SessionData(
                id=session_id,
                title=_session_title(first),
                created_at=first.created_at,
                updated_at=updated,
                task_ids=[task.data.task.id for task in tasks],
                task_count=len(tasks),
                last_task_id=last.id,
                last_task_status=last.status,
                history_incomplete=incomplete,
            ),
        )

    def _quarantine_sync(self, source: Path, code: str) -> None:
        assert self.paths is not None
        ensure_real_directory(self.paths.quarantine, boundary=self.paths.root)
        try:
            digest = hashlib.sha256()
            with source.open("rb") as handle:
                for chunk in iter(lambda: handle.read(64 * 1024), b""):
                    digest.update(chunk)
            identifier = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4()}"
            target = self.paths.quarantine / f"{identifier}-{source.name}"
            os.replace(source, target)
            atomic_write_json(
                self.paths.quarantine / f"{identifier}.json",
                QuarantineEnvelope(
                    data=QuarantineData(
                        source_name=source.name,
                        error_code=code,
                        quarantined_at=datetime.now(UTC),
                        sha256=digest.hexdigest(),
                    )
                ),
            )
        except OSError as exc:
            raise HistoryStorageUnavailable("Invalid history could not be quarantined") from exc

    def _write_index_sync(self, stored: SessionIndexEnvelope | None = None) -> None:
        sessions = sorted(
            (session.data for session in self.sessions.values()),
            key=lambda value: (value.updated_at, value.id),
            reverse=True,
        )
        data = SessionIndexData(sessions=sessions)
        if stored is not None and stored.data == data:
            self._index_revision = stored.revision
            return
        revision = max(self._index_revision, stored.revision if stored else 0) + 1
        atomic_write_json(
            self._workspace_path() / "index.json",
            SessionIndexEnvelope(revision=revision, data=data),
        )
        self._index_revision = revision

    async def _store_new(self, session: SessionEnvelope, task: TaskEnvelope) -> None:
        await asyncio.to_thread(self._store_new_sync, session, task)

    async def _store_append(self, session: SessionEnvelope, task: TaskEnvelope) -> None:
        await asyncio.to_thread(self._store_append_sync, session, task)

    def _store_append_sync(self, session: SessionEnvelope, task: TaskEnvelope) -> None:
        assert self.paths is not None
        task_path = self.paths.task(task.data.session_id, task.data.ordinal, task.data.task.id)
        session_path = self.paths.session(session.data.id) / "session.json"
        self._ensure_replacement_capacity_sync((task_path, task), (session_path, session))
        atomic_write_json(task_path, task)
        atomic_write_json(session_path, session)

    def _store_new_sync(self, session: SessionEnvelope, task: TaskEnvelope) -> None:
        assert self.paths is not None
        final = self.paths.session(session.data.id)
        staging = final.parent / f".session-tmp-{session.data.id}"
        try:
            (staging / "tasks").mkdir(parents=True, mode=0o700)
            task_path = staging / "tasks" / f"{task.data.ordinal:010d}-{task.data.task.id}.json"
            self._ensure_replacement_capacity_sync(
                (staging / "session.json", session), (task_path, task)
            )
            atomic_write_json(staging / "session.json", session)
            atomic_write_json(task_path, task)
            SessionEnvelope.model_validate_json((staging / "session.json").read_text("utf-8"))
            TaskEnvelope.model_validate_json(task_path.read_text("utf-8"))
            try:
                os.replace(staging, final)
            except OSError:
                final_session = _read_envelope(final / "session.json", SessionEnvelope)
                final_task = _read_envelope(
                    final / "tasks" / task_path.name,
                    TaskEnvelope,
                )
                if final_session != session or final_task != task:
                    raise
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    async def create_with_task(
        self, task: Task, trace: ExecutionTrace, session_id: str | None = None
    ) -> PersistedTaskData:
        persisted = await super().create_with_task(task, trace, session_id)
        try:
            await asyncio.to_thread(self._write_index_sync)
        except HistoryStorageUnavailable:
            # The Task/Session directory is authoritative; startup rebuilds this projection.
            pass
        return persisted

    async def _store_update(self, task: TaskEnvelope, session: SessionEnvelope) -> None:
        await asyncio.to_thread(self._store_update_sync, task, session)

    def _store_update_sync(self, task: TaskEnvelope, session: SessionEnvelope) -> None:
        assert self.paths is not None
        task_path = self.paths.task(
            task.data.session_id,
            task.data.ordinal,
            task.data.task.id,
        )
        session_path = self.paths.session(session.data.id) / "session.json"
        self._ensure_replacement_capacity_sync((task_path, task), (session_path, session))
        atomic_write_json(task_path, task)
        atomic_write_json(session_path, session)

    async def commit_task_event(self, task: Task, event: AgentEvent, trace: ExecutionTrace) -> None:
        await super().commit_task_event(task, event, trace)
        try:
            await asyncio.to_thread(self._write_index_sync)
        except HistoryStorageUnavailable:
            pass

    async def _store_delete(self, session: SessionEnvelope) -> None:
        await asyncio.to_thread(self._store_delete_sync, session)

    def _store_delete_sync(self, session: SessionEnvelope) -> None:
        assert self.paths is not None
        source = self.paths.session(session.data.id)
        if not source.is_dir() or path_is_link(source):
            raise SessionNotFound("Session was not found")
        trash = self._workspace_path() / "trash"
        batch = trash / str(uuid4())
        batch.mkdir(mode=0o700)
        target = batch / session.data.id
        moved: list[tuple[Path, Path]] = []
        try:
            os.replace(source, target)
            moved.append((source, target))
            if self.paths.backups.is_dir() and not path_is_link(self.paths.backups):
                for candidate in list(self.paths.backups.rglob(session.data.id)):
                    if not candidate.is_dir() or candidate.name != session.data.id:
                        continue
                    if path_is_link(candidate):
                        raise HistoryStorageUnavailable("History backup cannot contain links")
                    related_target = batch / f"backup-{uuid4()}"
                    os.replace(candidate, related_target)
                    moved.append((candidate, related_target))
            if self.paths.quarantine.is_dir() and not path_is_link(self.paths.quarantine):
                for candidate in list(self.paths.quarantine.iterdir()):
                    if not candidate.is_file() or path_is_link(candidate):
                        continue
                    try:
                        related = session.data.id in candidate.read_text(
                            encoding="utf-8", errors="ignore"
                        )
                    except OSError as exc:
                        raise HistoryStorageUnavailable(
                            "Quarantined history could not be checked for deletion"
                        ) from exc
                    if related:
                        related_target = batch / f"quarantine-{uuid4()}-{candidate.name}"
                        os.replace(candidate, related_target)
                        moved.append((candidate, related_target))
        except (OSError, HistoryStorageUnavailable) as exc:
            for original, moved_target in reversed(moved):
                try:
                    original.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.replace(moved_target, original)
                except OSError:
                    pass
            shutil.rmtree(batch, ignore_errors=True)
            raise HistoryStorageUnavailable("Session could not be moved to trash") from exc

    async def delete_session(self, session_id: str) -> None:
        await super().delete_session(session_id)
        await asyncio.to_thread(self._write_index_sync)
        await asyncio.to_thread(self._cleanup_trash_sync)

    async def close(self) -> None:
        if not self._opened:
            return
        lock, self._file_lock = self._file_lock, None
        self._opened = False
        if lock is not None:
            await asyncio.to_thread(lock.release)
