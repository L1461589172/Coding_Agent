import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from app.models.event import TERMINAL_EVENTS, AgentEvent, EventType


class EventPublisher(Protocol):
    async def publish(
        self,
        task_id: str,
        kind: EventType,
        payload: dict[str, Any],
        step: int = 0,
    ) -> AgentEvent: ...


@dataclass(frozen=True)
class EventLimits:
    max_payload_characters: int = 12_000
    max_history_characters: int = 256_000
    max_history_events: int = 512

    def __post_init__(self) -> None:
        if self.max_payload_characters < 256:
            raise ValueError("max_payload_characters must be at least 256")
        if self.max_history_characters < self.max_payload_characters + 1_024:
            raise ValueError("max_history_characters must cover one payload and its event envelope")
        if self.max_history_events < 1:
            raise ValueError("max_history_events must be positive")


def _serialized_characters(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def _bounded_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    if _serialized_characters(payload) <= limit:
        return deepcopy(payload)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    preserved_keys = (
        "call_id",
        "tool",
        "ok",
        "error_code",
        "cancelled",
        "path",
        "action",
        "exit_code",
        "termination_reason",
    )
    fixed: dict[str, Any] = {
        "payload_truncated": True,
        "original_characters": len(serialized),
        "original_keys": sorted(str(key)[:64] for key in payload)[:32],
        **{
            key: value[:128] if isinstance(value, str) else value
            for key in preserved_keys
            if (value := payload.get(key)) is not None
        },
    }

    def render(preview_characters: int) -> dict[str, Any]:
        return {**fixed, "preview": serialized[:preview_characters]}

    if _serialized_characters(render(0)) > limit:
        fixed = {
            "payload_truncated": True,
            "original_characters": len(serialized),
        }

    low, high = 0, len(serialized)
    while low < high:
        middle = (low + high + 1) // 2
        if _serialized_characters(render(middle)) <= limit:
            low = middle
        else:
            high = middle - 1
    bounded = render(low)
    if _serialized_characters(bounded) > limit:
        raise ValueError("Event payload metadata exceeds its configured limit")
    return bounded


class EventLog:
    """One task's replayable log. A condition avoids the replay/subscribe race."""

    def __init__(self, limits: EventLimits | None = None) -> None:
        self.limits = limits or EventLimits()
        self._events: list[AgentEvent] = []
        self._event_characters: list[int] = []
        self._history_characters = 0
        self._last_id = 0
        self._changed = asyncio.Condition()
        self.closed = False

    @property
    def last_id(self) -> int:
        return self._last_id

    @property
    def first_id(self) -> int:
        return int(self._events[0].id) if self._events else self._last_id + 1

    @property
    def history_characters(self) -> int:
        return self._history_characters

    def cursor_available(self, cursor: int) -> bool:
        if cursor < 0 or cursor > self.last_id:
            return False
        return cursor == 0 or cursor >= self.first_id - 1

    async def publish(
        self, task_id: str, kind: EventType, payload: dict[str, Any], step: int = 0
    ) -> AgentEvent:
        async with self._changed:
            if self.closed:
                raise RuntimeError("Cannot append events after task termination")
            self._last_id += 1
            event = AgentEvent(
                id=str(self._last_id),
                task_id=task_id,
                type=kind,
                payload=_bounded_payload(payload, self.limits.max_payload_characters),
                step=step,
            )
            self._events.append(event)
            characters = len(event.as_sse())
            self._event_characters.append(characters)
            self._history_characters += characters
            while len(self._events) > 1 and (
                len(self._events) > self.limits.max_history_events
                or self._history_characters > self.limits.max_history_characters
            ):
                self._events.pop(0)
                self._history_characters -= self._event_characters.pop(0)
            self.closed = kind in TERMINAL_EVENTS
            self._changed.notify_all()
            return event

    async def stream(self, after: int = 0, heartbeat: float = 15) -> AsyncIterator[str]:
        cursor = after
        while True:
            async with self._changed:
                if cursor >= self.last_id and not self.closed:
                    try:
                        await asyncio.wait_for(self._changed.wait(), timeout=heartbeat)
                    except TimeoutError:
                        pass
                batch = [event for event in self._events if int(event.id) > cursor]
                closed = self.closed
            for event in batch:
                cursor = int(event.id)
                yield event.as_sse()
            if closed:
                return
            if not batch:
                yield ": heartbeat\n\n"
