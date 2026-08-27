from pydantic import BaseModel, Field

from app.tools.base import ToolArgs, ToolResult, ToolSpec


class RunCommandArgs(ToolArgs):
    command: str = Field(min_length=1, max_length=4000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)


async def run_command(arguments: BaseModel) -> ToolResult:
    # Do not add subprocess execution until timeout/process cleanup is implemented.
    return ToolResult(
        ok=False,
        error_code="NOT_IMPLEMENTED",
        error_message="Shell 执行尚未实现；没有启动任何子进程。",
    )


def shell_spec() -> ToolSpec:
    return ToolSpec(
        "run_command", "Run a local command (not a sandbox)", RunCommandArgs, run_command
    )
