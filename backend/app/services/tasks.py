import asyncio

from app.agent.runtime import AgentRuntimeError, RuntimeNotReady, TaskRunner
from app.core.events import EventLimits, EventLog
from app.models.task import Task, TaskError, TaskStatus, utc_now
from app.services.trace import ExecutionTrace, TraceRecorder, build_task_summary


class TaskBusy(Exception):
    pass


class TaskCapacity(Exception):
    pass


class TaskManager:
    """Single-event-loop manager. Use one Uvicorn worker; no cross-process locks."""

    def __init__(
        self,
        runner: TaskRunner,
        max_tasks: int = 100,
        mode: str = "scaffold",
        event_limits: EventLimits | None = None,
    ) -> None:
        self.runner = runner
        self.max_tasks = max_tasks
        self.mode = mode
        self.event_limits = event_limits or EventLimits()
        self.tasks: dict[str, Task] = {}
        self.logs: dict[str, EventLog] = {}
        self.traces: dict[str, ExecutionTrace] = {}
        self._active: str | None = None
        self._job: asyncio.Task[None] | None = None

    def create(self, prompt: str) -> Task:
        # No await between the check and reservation: concurrent HTTP calls cannot interleave.
        if self._active is not None:
            raise TaskBusy()
        if len(self.tasks) >= self.max_tasks:
            raise TaskCapacity()
        task = Task(prompt=prompt, mode=self.mode)
        self.tasks[task.id] = task
        self.logs[task.id] = EventLog(self.event_limits)
        self.traces[task.id] = ExecutionTrace()
        self._active = task.id
        self._job = asyncio.create_task(self._execute(task))
        return task.model_copy(deep=True)

    def get(self, task_id: str) -> Task:
        return self.tasks[task_id].model_copy(deep=True)

    async def _execute(self, task: Task) -> None:
        log = self.logs[task.id]
        recorder = TraceRecorder(log, self.traces[task.id])
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
            task.summary = build_task_summary(task, self.traces[task.id])
            try:
                if task.status == TaskStatus.COMPLETED:
                    await log.publish(task.id, "task_completed", {"result": task.result})
                else:
                    await log.publish(
                        task.id,
                        "task_failed",
                        {
                            "error": task.error.model_dump() if task.error else None,
                        },
                    )
            finally:
                self._active = None

    async def close(self) -> None:
        if self._job and not self._job.done():
            self._job.cancel()
        if self._job:
            await asyncio.gather(self._job, return_exceptions=True)
        # Cancellation can occur before _execute starts, so its finally may never run.
        if self._active is not None:
            task = self.tasks[self._active]
            task.status = TaskStatus.FAILED
            task.finished_at = utc_now()
            task.error = TaskError(code="SERVER_SHUTDOWN", message="Service is shutting down")
            task.summary = build_task_summary(task, self.traces[task.id])
            await self.logs[task.id].publish(
                task.id, "task_failed", {"error": task.error.model_dump()}
            )
            self._active = None
