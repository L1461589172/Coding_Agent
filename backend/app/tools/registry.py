from typing import Any

from pydantic import ValidationError

from app.tools.base import ToolResult, ToolSpec
from app.tools.files import file_specs
from app.tools.read_only import ReadError, ReadLimits
from app.tools.search import search_spec
from app.tools.shell import shell_spec
from app.tools.workspace import Workspace, WorkspaceError


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("Duplicate tool names")

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.schema() for spec in self._specs.values()]

    def availability(self) -> dict[str, str]:
        return {
            spec.name: "ready" if spec.implemented else "not_implemented"
            for spec in self._specs.values()
        }

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(ok=False, error_code="UNKNOWN_TOOL", error_message="Unknown tool")
        try:
            parsed = spec.arguments.model_validate(arguments)
        except ValidationError:
            # Never echo raw input into errors: arguments may contain secrets.
            return ToolResult(
                ok=False,
                error_code="INVALID_ARGUMENTS",
                error_message="Arguments do not match the tool schema",
            )
        try:
            return await spec.handler(parsed)
        except (WorkspaceError, ReadError) as exc:
            return ToolResult(ok=False, error_code=exc.code, error_message=str(exc))
        except FileNotFoundError:
            return ToolResult(ok=False, error_code="NOT_FOUND", error_message="Path does not exist")
        except NotADirectoryError:
            return ToolResult(
                ok=False, error_code="NOT_DIRECTORY", error_message="Expected directory"
            )
        except IsADirectoryError:
            return ToolResult(
                ok=False, error_code="NOT_FILE", error_message="Expected regular file"
            )
        except PermissionError:
            return ToolResult(
                ok=False, error_code="PERMISSION_DENIED", error_message="Access denied"
            )
        except OSError:
            return ToolResult(
                ok=False, error_code="IO_ERROR", error_message="Filesystem operation failed"
            )
        except Exception:
            return ToolResult(
                ok=False,
                error_code="TOOL_ERROR",
                error_message="Tool failed; raw exception details are not exposed",
            )


def create_registry(workspace: Workspace, limits: ReadLimits | None = None) -> ToolRegistry:
    policy = limits or ReadLimits()
    return ToolRegistry(
        [*file_specs(workspace, policy), search_spec(workspace, policy), shell_spec()]
    )
