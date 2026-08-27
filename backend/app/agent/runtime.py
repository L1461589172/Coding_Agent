from typing import Protocol

from app.core.events import EventLog
from app.models.task import Task
from app.tools.registry import ToolRegistry
from app.tools.workspace import Workspace


class RuntimeNotReady(Exception):
    """Expected failure for a task submitted to the foundation-only runtime."""


class TaskRunner(Protocol):
    async def run(self, task: Task, events: EventLog) -> str: ...


class AgentRuntime:
    def __init__(self, workspace: Workspace, tools: ToolRegistry) -> None:
        self.workspace = workspace
        self.tools = tools

    async def run(self, task: Task, events: EventLog) -> str:
        await events.publish(
            task.id,
            "assistant_message",
            {
                "message": "基础框架已连通。Agent 尚未实现；本次未操作文件或执行命令。",
                "mode": "scaffold",
            },
        )
        raise RuntimeNotReady()
