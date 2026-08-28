import json
from typing import Any, Literal


class StopController:
    """Deterministic policy used by the Agent Loop before each action."""

    def __init__(self, max_steps: int = 20) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.max_steps = max_steps
        self._previous: str | None = None
        self._repeated = 0

    def reached_step_limit(self, steps_completed: int) -> bool:
        return steps_completed >= self.max_steps

    def observe(self, name: str, arguments: dict[str, Any]) -> Literal["continue", "warn", "stop"]:
        signature = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        self._repeated = self._repeated + 1 if signature == self._previous else 1
        self._previous = signature
        if self._repeated >= 4:
            return "stop"
        return "warn" if self._repeated == 3 else "continue"
