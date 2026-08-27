import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.models.event import TERMINAL_EVENTS, AgentEvent, EventType


class EventLog:
    """One task's replayable log. A condition avoids the replay/subscribe race."""

    def __init__(self) -> None:
        self._events: list[AgentEvent] = []
        self._changed = asyncio.Condition()
        self.closed = False

    @property
    def last_id(self) -> int:
        return len(self._events)

    async def publish(
        self, task_id: str, kind: EventType, payload: dict[str, Any], step: int = 0
    ) -> AgentEvent:
        async with self._changed:
            if self.closed:
                raise RuntimeError("Cannot append events after task termination")
            event = AgentEvent(
                id=str(self.last_id + 1), task_id=task_id, type=kind, payload=payload, step=step
            )
            self._events.append(event)
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
                batch = self._events[cursor:]
                closed = self.closed
            for event in batch:
                cursor = int(event.id)
                yield event.as_sse()
            if closed:
                return
            if not batch:
                yield ": heartbeat\n\n"
