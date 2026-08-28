import json
from copy import deepcopy
from dataclasses import dataclass
from math import ceil
from typing import Any


class ContextBudgetError(Exception):
    """The required base or latest complete round cannot fit the model context."""


@dataclass(frozen=True)
class ContextBudget:
    max_characters: int = 80_000
    max_tokens: int = 20_000
    max_tool_result_characters: int = 12_000

    def __post_init__(self) -> None:
        if self.max_characters < 1 or self.max_tokens < 1:
            raise ValueError("Context character and token budgets must be positive")
        if self.max_tool_result_characters < 256:
            raise ValueError("Tool result context budget must be at least 256 characters")


@dataclass(frozen=True)
class ContextSize:
    characters: int
    tokens: int


def estimate_tokens(text: str) -> int:
    """Deterministic approximation: non-ASCII chars cost one, ASCII costs one per four."""

    ascii_characters = sum(character.isascii() for character in text)
    non_ascii_characters = len(text) - ascii_characters
    return non_ascii_characters + ceil(ascii_characters / 4)


def measure_context(messages: list[dict[str, Any]]) -> ContextSize:
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return ContextSize(characters=len(serialized), tokens=estimate_tokens(serialized))


def measure_model_input(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> ContextSize:
    if tools is None:
        return measure_context(messages)
    serialized = json.dumps(
        {"messages": messages, "tools": tools}, ensure_ascii=False, separators=(",", ":")
    )
    return ContextSize(characters=len(serialized), tokens=estimate_tokens(serialized))


def _fits(
    messages: list[dict[str, Any]],
    budget: ContextBudget,
    tools: list[dict[str, Any]] | None,
) -> bool:
    size = measure_model_input(messages, tools)
    return size.characters <= budget.max_characters and size.tokens <= budget.max_tokens


def _truncate_tool_content(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    try:
        original = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        original = {}
    fixed = {
        "context_truncated": True,
        "original_characters": len(content),
        "ok": original.get("ok") if isinstance(original, dict) else None,
        "error_code": original.get("error_code") if isinstance(original, dict) else None,
        "tool_truncated": original.get("truncated") if isinstance(original, dict) else None,
    }

    def render(preview_characters: int) -> str:
        return json.dumps(
            {**fixed, "preview": content[:preview_characters]},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    low, high = 0, len(content)
    while low < high:
        middle = (low + high + 1) // 2
        if len(render(middle)) <= limit:
            low = middle
        else:
            high = middle - 1
    truncated = render(low)
    if len(truncated) > limit:
        raise ContextBudgetError("Tool result metadata cannot fit its context budget")
    return truncated


class Conversation:
    """Keep complete rounds so context selection cannot orphan a tool result."""

    def __init__(self, system: str, prompt: str, budget: ContextBudget | None = None) -> None:
        self.base = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        self.rounds: list[list[dict[str, Any]]] = []
        self.budget = budget or ContextBudget()

    def append_round(self, messages: list[dict[str, Any]]) -> None:
        if not messages or messages[0].get("role") != "assistant":
            raise ValueError("A round must begin with an assistant message")
        calls = messages[0].get("tool_calls", [])
        if not isinstance(calls, list) or any(
            not isinstance(call, dict) or not isinstance(call.get("id"), str) for call in calls
        ):
            raise ValueError("Assistant tool calls must have string ids")
        expected = [call["id"] for call in calls]
        actual = [message.get("tool_call_id") for message in messages[1:]]
        if (
            len(set(expected)) != len(expected)
            or expected != actual
            or any(message.get("role") != "tool" for message in messages[1:])
        ):
            raise ValueError("Every tool call must have exactly one ordered result")
        self.rounds.append(deepcopy(messages))

    def build_context(
        self,
        recent_rounds: int = 8,
        budget: ContextBudget | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if recent_rounds < 1:
            raise ValueError("recent_rounds must be positive")
        policy = budget or self.budget
        base = deepcopy(self.base)
        if not _fits(base, policy, tools):
            raise ContextBudgetError("System prompt and original task exceed the context budget")

        selected: list[list[dict[str, Any]]] = []
        for conversation_round in reversed(self.rounds[-recent_rounds:]):
            fitted = self._fit_round(conversation_round, selected, policy, tools)
            if fitted is None:
                if not selected:
                    raise ContextBudgetError("Latest complete round exceeds the context budget")
                break
            selected.insert(0, fitted)
        return base + [message for conversation_round in selected for message in conversation_round]

    def _fit_round(
        self,
        conversation_round: list[dict[str, Any]],
        newer_rounds: list[list[dict[str, Any]]],
        budget: ContextBudget,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        base = deepcopy(self.base)
        newer = [message for item in newer_rounds for message in item]

        def with_tool_limit(limit: int) -> list[dict[str, Any]]:
            candidate = deepcopy(conversation_round)
            for message in candidate:
                if message.get("role") == "tool" and isinstance(message.get("content"), str):
                    message["content"] = _truncate_tool_content(message["content"], limit)
            return candidate

        high = budget.max_tool_result_characters
        candidate = with_tool_limit(high)
        if _fits(base + candidate + newer, budget, tools):
            return candidate

        low = 256
        candidate = with_tool_limit(low)
        if not _fits(base + candidate + newer, budget, tools):
            return None

        while low < high:
            middle = (low + high + 1) // 2
            attempt = with_tool_limit(middle)
            if _fits(base + attempt + newer, budget, tools):
                low = middle
                candidate = attempt
            else:
                high = middle - 1
        return candidate
