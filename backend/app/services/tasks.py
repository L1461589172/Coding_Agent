import asyncio

from app.agent.runtime import AgentRuntimeError, RuntimeNotReady, TaskRunner
from app.core.events import EventLimits, EventLog
from app.history.errors import HistoryCapacity, HistoryError
from app.history.repository import HistoryRepository, InMemoryHistoryRepository
from app.models.task import Task, TaskError, TaskStatus, utc_now
from app.services.trace import ExecutionTrace, TraceRecorder, build_task_summary


class TaskBusy(Exception):
    pass


class TaskCapacity(Exception):
    pass


class TaskPersistenceUnavailable(Exception):
    pass


class TaskManager:
    """Single-event-loop manager. Use one Uvicorn worker; no cross-process locks."""

    def __init__(
        self,
        runner: TaskRunner,
        max_tasks: int = 100,
        mode: str = "scaffold",
        event_limits: EventLimits | None = None,
        repository: HistoryRepository | None = None,
    ) -> None:
        self.runner = runner
        self.max_tasks = max_tasks
        self.mode = mode
        self.event_limits = event_limits or EventLimits()
        self.repository = repository or InMemoryHistoryRepository(
            self.event_limits,
            max_sessions=max_tasks,
        )
        self.tasks: dict[str, Task] = {}
        self.logs: dict[str, EventLog] = {}
        self.traces: dict[str, ExecutionTrace] = {}
        self._active: str | None = None
        self._job: asyncio.Task[None] | None = None
        self._create_lock = asyncio.Lock()

    async def create(self, prompt: str) -> Task:
        async with self._create_lock:
            if self._active is not None or self.repository.has_unfinished_task():
                raise TaskBusy()
            task = Task(prompt=prompt, mode=self.mode)
            trace = ExecutionTrace()
            try:
                await self.repository.create_with_task(task, trace)
            except HistoryCapacity as exc:
                raise TaskCapacity() from exc
            except HistoryError as exc:
                raise TaskPersistenceUnavailable() from exc
            self.tasks[task.id] = task
            self.logs[task.id] = EventLog(self.event_limits)
            self.traces[task.id] = trace
            self._active = task.id
            self._job = asyncio.create_task(self._execute(task))
            return task.model_copy(deep=True)

    def get(self, task_id: str) -> Task:
        return self.repository.get_task(task_id)

    def get_log(self, task_id: str) -> EventLog:
        log = self.logs.get(task_id)
        if log is not None:
            return log
        persisted = self.repository.get_persisted_task(task_id)
        log = EventLog.from_persisted(
            persisted.events,
            persisted.last_event_id,
            self.event_limits,
        )
        self.logs[task_id] = log
        return log

    async def _execute(self, task: Task) -> None:
        log = self.logs[task.id]
        trace = self.traces[task.id]

        async def commit(event, updated_trace):
            await self.repository.commit_task_event(task, event, updated_trace)

        recorder = TraceRecorder(log, trace, commit)
        try:
            task.status = TaskStatus.RUNNING
            task.started_at = utc_now()
            await recorder.publish(task.id, "task_started", {"mode": task.mode})
            task.result = await self.runner.run(task.model_copy(deep=True), recorder)
            task.status = TaskStatus.COMPLETED
        except RuntimeNotReady:
            task.status = TaskStatus.FAILED
            task.error = TaskError(
                code="NOT_IMPLEMENTED",
                message=(
                    "Agent Loop 已就绪，但模型配置不完整；编程任务未执行。"
                    "请设置 API Key、Base URL 和模型名后重启服务。"
                ),
            )
        except AgentRuntimeError as exc:
            task.status = TaskStatus.FAILED
            task.error = TaskError(code=exc.code, message=str(exc))
        except asyncio.CancelledError:
            task.status = TaskStatus.FAILED
            task.error = TaskError(code="SERVER_SHUTDOWN", message="Service is shutting down")
        except Exception:
            task.status = TaskStatus.FAILED
            task.error = TaskError(
                code="RUNTIME_ERROR", message="Runtime failed; details are hidden"
            )
        finally:
            task.finished_at = utc_now()
            task.summary = build_task_summary(task, trace)
            terminal_committed = False
            try:
                if task.status == TaskStatus.COMPLETED:
                    payload = {"result": task.result}
                else:
                    payload = {"error": task.error.model_dump() if task.error else None}
                kind = "task_completed" if task.status == TaskStatus.COMPLETED else "task_failed"

                async def persist_terminal(event):
                    await self.repository.commit_task_event(task, event, trace)

                await log.publish(
                    task.id,
                    kind,
                    payload,
                    before_notify=persist_terminal,
                )
                terminal_committed = True
            finally:
                # A failed durable commit must not make the process accept a new
                # task while the repository still records this one as active.
                if terminal_committed:
                    self._active = None
                    self.tasks.pop(task.id, None)
                    self.traces.pop(task.id, None)
                    self.logs.pop(task.id, None)

    async def close(self) -> None:
        if self._job and not self._job.done():
            self._job.cancel()
        if self._job:
            await asyncio.gather(self._job, return_exceptions=True)
        # Cancellation can occur before _execute starts, so its finally may never run.
        try:
            if self._active is not None:
                task_id = self._active
                task = self.tasks[task_id]
                task.status = TaskStatus.FAILED
                task.finished_at = utc_now()
                task.error = TaskError(code="SERVER_SHUTDOWN", message="Service is shutting down")
                trace = self.traces[task.id]
                task.summary = build_task_summary(task, trace)

                async def persist_terminal(event):
                    await self.repository.commit_task_event(task, event, trace)

                await self.logs[task.id].publish(
                    task.id,
                    "task_failed",
                    {"error": task.error.model_dump()},
                    before_notify=persist_terminal,
                )
                self._active = None
                self.tasks.pop(task_id, None)
                self.traces.pop(task_id, None)
                self.logs.pop(task_id, None)
        finally:
            await self.repository.close()
