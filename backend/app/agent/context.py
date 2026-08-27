from copy import deepcopy
from typing import Any


class Conversation:
    """Keep complete rounds so context selection cannot orphan a tool result."""

    def __init__(self, system: str, prompt: str) -> None:
        self.base = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        self.rounds: list[list[dict[str, Any]]] = []

    def append_round(self, messages: list[dict[str, Any]]) -> None:
        if not messages or messages[0].get("role") != "assistant":
            raise ValueError("A round must begin with an assistant message")
        calls = messages[0].get("tool_calls", [])
        expected = [call["id"] for call in calls]
        actual = [message.get("tool_call_id") for message in messages[1:]]
        if (
            len(set(expected)) != len(expected)
            or expected != actual
            or any(message.get("role") != "tool" for message in messages[1:])
        ):
            raise ValueError("Every tool call must have exactly one ordered result")
        self.rounds.append(deepcopy(messages))

    def build_context(self, recent_rounds: int = 8) -> list[dict[str, Any]]:
        if recent_rounds < 1:
            raise ValueError("recent_rounds must be positive")
        # Character/token budgets and per-tool truncation are intentionally still M2 work.
        return deepcopy(self.base + [m for r in self.rounds[-recent_rounds:] for m in r])
