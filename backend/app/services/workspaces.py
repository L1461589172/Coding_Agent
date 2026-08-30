from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.agent.context import ContextBudget
from app.agent.llm import OpenAICompatibleLLMClient
from app.agent.runtime import AgentRuntime, TaskRunner
from app.core.config import APPLICATION_ROOT, Settings
from app.core.events import EventLimits
from app.history.atomic import atomic_write_json
from app.history.errors import HistoryError, HistoryStorageUnavailable
from app.history.paths import path_is_link
from app.history.repository import JsonHistoryRepository
from app.models.workspace import WorkspaceInfo, WorkspaceState
from app.services.tasks import TaskManager
from app.tools.registry import ToolRegistry, create_registry
from app.tools.workspace import Workspace, WorkspaceError

_CATALOG_VERSION = 1
_MAX_RECENT_WORKSPACES = 10
_MAX_CATALOG_BYTES = 64 * 1024


class WorkspaceBusy(Exception):
    pass


class WorkspaceInvalid(Exception):
    pass


class WorkspaceSwitchUnavailable(Exception):
    pass


def _canonical_key(path: Path) -> str:
    return os.path.normcase(str(path))


def _workspace_info(path: Path) -> WorkspaceInfo:
    return WorkspaceInfo(name=path.name or str(path), path=str(path))


class RecentWorkspaceCatalog:
    """Bounded local navigation hints; never scans the filesystem for projects."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._paths: list[Path] = []

    async def open(self) -> None:
        self._paths = await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> list[Path]:
        if not self.path.exists() or path_is_link(self.path):
            return []
        try:
            if self.path.stat().st_size > _MAX_CATALOG_BYTES:
                return []
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(payload, dict) or payload.get("version") != _CATALOG_VERSION:
            return []
        values = payload.get("recent")
        if not isinstance(values, list):
            return []
        loaded: list[Path] = []
        seen: set[str] = set()
        for value in values[:_MAX_RECENT_WORKSPACES]:
            if not isinstance(value, str) or not value or len(value) > 4096:
                continue
            try:
                resolved = Path(value).resolve(strict=True)
            except OSError:
                continue
            if not resolved.is_dir():
                continue
            key = _canonical_key(resolved)
            if key not in seen:
                seen.add(key)
                loaded.append(resolved)
        return loaded

    async def record(self, workspace: Path) -> None:
        key = _canonical_key(workspace)
        self._paths = [
            workspace,
            *(path for path in self._paths if _canonical_key(path) != key),
        ][:_MAX_RECENT_WORKSPACES]
        try:
            await asyncio.to_thread(
                atomic_write_json,
                self.path,
                {
                    "version": _CATALOG_VERSION,
                    "recent": [str(path) for path in self._paths],
                },
            )
        except HistoryStorageUnavailable:
            # Recent paths are an optional navigation aid, not authoritative data.
            pass

    def state(self, current: Path) -> WorkspaceState:
        paths = [current]
        current_key = _canonical_key(current)
        paths.extend(path for path in self._paths if _canonical_key(path) != current_key)
        return WorkspaceState(
            current=_workspace_info(current),
            recent=[_workspace_info(path) for path in paths[:_MAX_RECENT_WORKSPACES]],
        )


@dataclass
class WorkspaceResources:
    workspace: Workspace
    tools: ToolRegistry
    runtime: TaskRunner
    runtime_to_close: AgentRuntime | None
    history: JsonHistoryRepository
    tasks: TaskManager | None = None


class WorkspaceService:
    """Owns one active Workspace resource graph and switches it transactionally."""

    def __init__(
        self,
        config: Settings,
        initial_workspace: Workspace,
        runner: TaskRunner | None = None,
    ) -> None:
        self.config = config
        self.initial_workspace = initial_workspace
        self.injected_runner = runner
        self.lock = asyncio.Lock()
        self.event_limits = EventLimits(
            max_payload_characters=config.event_max_payload_characters,
            max_history_characters=config.event_max_history_characters,
            max_history_events=config.event_max_history_events,
        )
        self.catalog = RecentWorkspaceCatalog(config.resolved_history_dir / "workspaces.json")
        self._current: WorkspaceResources | None = None

    @property
    def current(self) -> WorkspaceResources:
        if self._current is None or self._current.tasks is None:
            raise RuntimeError("Workspace service is not open")
        return self._current

    @property
    def state(self) -> WorkspaceState:
        return self.catalog.state(self.current.workspace.root)

    async def open(self) -> None:
        await self.catalog.open()
        resources = self._prepare(self.initial_workspace)
        try:
            await self._open_resources(resources)
        except BaseException:
            await self._close_runtime(resources)
            raise
        self._current = resources
        await self.catalog.record(resources.workspace.root)

    def _runtime(
        self, workspace: Workspace, tools: ToolRegistry
    ) -> tuple[TaskRunner, AgentRuntime | None]:
        if self.injected_runner is not None:
            return self.injected_runner, None
        llm = (
            OpenAICompatibleLLMClient.from_settings(self.config)
            if self.config.model_configured
            else None
        )
        runtime = AgentRuntime(
            workspace,
            tools,
            llm,
            max_steps=self.config.max_steps,
            context_budget=ContextBudget(
                max_characters=self.config.context_max_characters,
                max_tokens=self.config.context_max_tokens,
                max_tool_result_characters=self.config.tool_result_max_characters,
            ),
            recent_rounds=self.config.context_recent_rounds,
            max_consecutive_llm_errors=self.config.max_consecutive_llm_errors,
            max_consecutive_runtime_errors=self.config.max_consecutive_runtime_errors,
            max_consecutive_command_timeouts=self.config.max_consecutive_command_timeouts,
        )
        return runtime, runtime

    def _prepare(self, workspace: Workspace) -> WorkspaceResources:
        tools = create_registry(workspace)
        runtime, runtime_to_close = self._runtime(workspace, tools)
        history = JsonHistoryRepository(
            self.config.resolved_history_dir,
            workspace.root,
            self.event_limits,
            application_root=APPLICATION_ROOT if self.config.history_dir is None else None,
            max_sessions=self.config.history_max_sessions,
            max_tasks_per_session=self.config.history_max_tasks_per_session,
            backup_limit=self.config.history_backup_limit,
            backup_max_bytes=self.config.history_backup_max_bytes,
            max_bytes=self.config.history_max_bytes,
        )
        return WorkspaceResources(workspace, tools, runtime, runtime_to_close, history)

    async def _open_resources(self, resources: WorkspaceResources) -> None:
        try:
            await resources.history.open()
            await resources.history.reconcile_interrupted()
        except BaseException:
            await resources.history.close()
            raise
        mode = (
            "agent"
            if self.injected_runner is not None or resources.runtime_to_close.ready
            else "scaffold"
        )
        resources.tasks = TaskManager(
            resources.runtime,
            self.config.max_tasks,
            mode,
            self.event_limits,
            repository=resources.history,
        )

    def publish(self, state: object) -> None:
        current = self.current
        state.workspace = current.workspace
        state.tools = current.tools
        state.tasks = current.tasks
        state.agent_ready = current.tasks.mode == "agent"
        state.mode = current.tasks.mode

    async def _close_runtime(self, resources: WorkspaceResources) -> None:
        if resources.runtime_to_close is not None:
            await resources.runtime_to_close.close()

    async def switch(self, path: str) -> WorkspaceState:
        async with self.lock:
            old = self.current
            if old.tasks.busy:
                raise WorkspaceBusy()
            try:
                requested = Path(path)
                if not requested.is_absolute():
                    raise WorkspaceInvalid()
                candidate_workspace = Workspace(requested)
            except (OSError, WorkspaceError, ValueError) as exc:
                raise WorkspaceInvalid() from exc
            if _canonical_key(candidate_workspace.root) == _canonical_key(old.workspace.root):
                await self.catalog.record(old.workspace.root)
                return self.state

            candidate = self._prepare(candidate_workspace)
            try:
                await old.tasks.close()
            except (HistoryError, OSError) as exc:
                await self._close_runtime(candidate)
                try:
                    await old.history.open()
                except (HistoryError, OSError) as rollback_error:
                    raise WorkspaceSwitchUnavailable(
                        "The current workspace could not be restored"
                    ) from rollback_error
                raise WorkspaceSwitchUnavailable(
                    "The current workspace could not be closed"
                ) from exc
            try:
                await self._open_resources(candidate)
            except (HistoryError, OSError, ValueError) as exc:
                await self._close_runtime(candidate)
                try:
                    await old.history.open()
                except (HistoryError, OSError) as rollback_error:
                    raise WorkspaceSwitchUnavailable(
                        "Workspace switch failed and the previous history could not be restored"
                    ) from rollback_error
                raise WorkspaceSwitchUnavailable("Workspace could not be opened") from exc

            self._current = candidate
            await self._close_runtime(old)
            await self.catalog.record(candidate_workspace.root)
            return self.state

    async def close(self) -> None:
        if self._current is None:
            return
        current, self._current = self._current, None
        try:
            if current.tasks is not None:
                await current.tasks.close()
            else:
                await current.history.close()
        finally:
            await self._close_runtime(current)
