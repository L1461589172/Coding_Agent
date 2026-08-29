import asyncio

import pytest
from app.core.events import EventLimits, EventLog


def test_live_subscription_then_replay():
    async def scenario():
        log = EventLog()
        stream = log.stream(heartbeat=1)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await log.publish("task", "task_started", {})
        first = await asyncio.wait_for(pending, timeout=2)
        assert first.startswith("id: 1\n")
        await log.publish("task", "task_failed", {"message": "line1\nline2"})
        assert "id: 2\n" in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        replay = [chunk async for chunk in log.stream(after=1)]
        assert len(replay) == 1
        assert replay[0].count("data: ") == 1
        with pytest.raises(RuntimeError):
            await log.publish("task", "task_started", {})

    asyncio.run(scenario())


def test_heartbeat_and_reader_disconnect():
    async def scenario():
        log = EventLog()
        stream = log.stream(heartbeat=0.01)
        assert await asyncio.wait_for(anext(stream), timeout=2) == ": heartbeat\n\n"
        await stream.aclose()
        await log.publish("task", "task_failed", {})
        assert log.closed

    asyncio.run(scenario())


def test_persisted_replay_applies_a_lower_restart_limit_without_renumbering():
    async def scenario():
        original = EventLog(
            EventLimits(
                max_payload_characters=256,
                max_history_characters=4_000,
                max_history_events=10,
            )
        )
        for number in range(5):
            await original.publish("task", "assistant_message", {"number": number})
        await original.publish("task", "task_completed", {"result": "done"})

        restored = EventLog.from_persisted(
            original._events,
            original.last_id,
            EventLimits(
                max_payload_characters=256,
                max_history_characters=4_000,
                max_history_events=3,
            ),
        )
        assert [int(event.id) for event in restored._events] == [4, 5, 6]
        assert restored.last_id == 6
        assert restored.closed is True
        assert restored.cursor_available(2) is False
        assert restored.cursor_available(3) is True

    asyncio.run(scenario())
