import json
from typing import Any, Literal

from app.tools.base import ToolResult


class StopController:
    """Deterministic policy used by the Agent Loop before each action."""

    RUNTIME_ERROR_CODES = frozenset(
        {
            "TOOL_ERROR",
            "IO_ERROR",
            "PERMISSION_DENIED",
            "COMMAND_START_FAILED",
            "COMMAND_CLEANUP_FAILED",
        }
    )

    def __init__(
        self,
        max_steps: int = 20,
        *,
        max_consecutive_llm_errors: int = 3,
        max_consecutive_runtime_errors: int = 3,
        max_consecutive_command_timeouts: int = 3,
    ) -> None:
        if (
            min(
                max_steps,
                max_consecutive_llm_errors,
                max_consecutive_runtime_errors,
                max_consecutive_command_timeouts,
            )
            < 1
        ):
            raise ValueError("Stop limits must be positive")
        self.max_steps = max_steps
        self.max_consecutive_llm_errors = max_consecutive_llm_errors
        self.max_consecutive_runtime_errors = max_consecutive_runtime_errors
        self.max_consecutive_command_timeouts = max_consecutive_command_timeouts
        self._previous: str | None = None
        self._repeated = 0
        self._llm_errors = 0
        self._runtime_errors = 0
        self._command_timeouts = 0

    def reached_step_limit(self, steps_completed: int) -> bool:
        return steps_completed >= self.max_steps

    def observe(self, name: str, arguments: dict[str, Any]) -> Literal["continue", "warn", "stop"]:
        signature = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        self._repeated = self._repeated + 1 if signature == self._previous else 1
        self._previous = signature
        if self._repeated >= 4:
            return "stop"
        return "warn" if self._repeated == 3 else "continue"

    def observe_llm_error(self) -> bool:
        """Return true when consecutive model failures reached the task threshold."""

        self._llm_errors += 1
        return self._llm_errors >= self.max_consecutive_llm_errors

    def reset_llm_errors(self) -> None:
        self._llm_errors = 0

    @property
    def consecutive_llm_errors(self) -> int:
        return self._llm_errors

    def observe_result(self, result: ToolResult) -> str | None:
        """Track infrastructure failures separately from model-correctable tool errors."""

        if result.error_code == "COMMAND_TIMEOUT":
            self._command_timeouts += 1
        else:
            self._command_timeouts = 0

        if result.error_code in self.RUNTIME_ERROR_CODES:
            self._runtime_errors += 1
        else:
            self._runtime_errors = 0

        if self._command_timeouts >= self.max_consecutive_command_timeouts:
            return "CONSECUTIVE_COMMAND_TIMEOUTS"
        if self._runtime_errors >= self.max_consecutive_runtime_errors:
            return "CONSECUTIVE_RUNTIME_ERRORS"
        return None
