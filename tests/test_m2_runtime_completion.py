import asyncio
import ctypes
import json
import os
import threading
from copy import deepcopy

from app.agent.llm import LLMError, ModelReply, ToolCall
from app.agent.runtime import AgentRuntime
from app.core.config import Settings
from app.core.events import EventLimits, EventLog
from app.main import create_app
from app.services.tasks import TaskManager
from app.tools.base import ToolArgs, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry, create_registry
from app.tools.workspace import Workspace
from fastapi.testclient import TestClient


class FakeLLM:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        index = len(self.calls) - 1
        reply = self.replies(index, messages)
        if isinstance(reply, Exception):
            raise reply
        return reply.model_copy(deep=True)

    async def close(self):
        pass


def call(call_id: str, name: str, arguments: dict) -> ModelReply:
    return ModelReply(tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def decoded_events(chunks: list[str]) -> list[dict]:
    return [
        json.loads(line[6:])
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: ")
    ]


def process_running(pid: int) -> bool:
    if os.name == "nt":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_event_log_bounds_payload_and_history_with_stable_ids():
    async def scenario():
        log = EventLog(
            EventLimits(
                max_payload_characters=256,
                max_history_characters=2_000,
                max_history_events=3,
            )
        )
        for _number in range(5):
            await log.publish("task", "assistant_message", {"message": "x" * 1_000})
        await log.publish("task", "task_failed", {"error": {"code": "fixture"}})

        replay = decoded_events([chunk async for chunk in log.stream()])
        assert [event["id"] for event in replay] == ["4", "5", "6"]
        assert replay[0]["payload"]["payload_truncated"] is True
        assert log.first_id == 4 and log.last_id == 6
        assert log.history_characters <= 2_000
        assert log.cursor_available(0) and log.cursor_available(3)
        assert not log.cursor_available(2)

    asyncio.run(scenario())


def test_runtime_publishes_tool_file_and_command_events(tmp_path):
    fake = FakeLLM(
        lambda index, messages: [
            call(
                "write-id",
                "write_file",
                {"path": "note.txt", "content": "created by agent\n"},
            ),
            call("command-id", "run_command", {"command": "echo verified"}),
            ModelReply(content="Created the file and verified the command."),
        ][index]
    )
    runtime = AgentRuntime(Workspace(tmp_path), create_registry(Workspace(tmp_path)), fake)

    async def scenario():
        manager = TaskManager(runtime, mode="agent")
        task = manager.create("Create and verify a file")
        events = decoded_events([chunk async for chunk in manager.logs[task.id].stream()])
        types = [event["type"] for event in events]
        assert types.count("tool_started") == 2
        assert types.count("tool_finished") == 2
        assert "file_changed" in types and "command_finished" in types

        started = next(
            event
            for event in events
            if event["type"] == "tool_started" and event["payload"]["call_id"] == "write-id"
        )
        assert started["payload"]["arguments"]["content"] == {
            "redacted": True,
            "characters": 17,
        }
        assert (
            next(event for event in events if event["type"] == "file_changed")["payload"]["path"]
            == "note.txt"
        )
        command = next(event for event in events if event["type"] == "command_finished")
        assert command["payload"]["call_id"] == "command-id"
        assert command["payload"]["exit_code"] == 0
        assert command["payload"]["cleanup_ok"] is True
        assert all(event["step"] > 0 for event in events if event["type"].startswith("tool_"))
        await manager.close()

    asyncio.run(scenario())


def test_api_reports_expired_event_cursor(tmp_path):
    class NoisyRunner:
        async def run(self, task, events):
            for number in range(5):
                await events.publish(task.id, "assistant_message", {"number": number})
            return "done"

    app = create_app(
        Settings(
            workspace=tmp_path,
            event_max_payload_characters=256,
            event_max_history_characters=4_000,
            event_max_history_events=3,
        ),
        runner=NoisyRunner(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "emit events"}).json()
        initial = client.get(f"/api/tasks/{task['id']}/events")
        assert initial.status_code == 200
        assert initial.text.count("data: ") == 3
        assert client.get(f"/api/tasks/{task['id']}/events?after=1").status_code == 410


def test_retryable_llm_errors_recover_then_reset(tmp_path):
    def replies(index, messages):
        if index < 2:
            return LLMError("LLM_NETWORK_ERROR", "temporary", retryable=True)
        return ModelReply(content="Recovered safely.")

    fake = FakeLLM(replies)
    runtime = AgentRuntime(
        Workspace(tmp_path),
        create_registry(Workspace(tmp_path)),
        fake,
        max_consecutive_llm_errors=3,
    )

    async def scenario():
        manager = TaskManager(runtime, mode="agent")
        task = manager.create("Recover")
        events = decoded_events([chunk async for chunk in manager.logs[task.id].stream()])
        assert manager.get(task.id).status == "COMPLETED"
        assert len(fake.calls) == 3
        recovery = [event for event in events if event["payload"].get("mode") == "recovery"]
        assert [event["payload"]["consecutive_errors"] for event in recovery] == [1, 2]
        await manager.close()

    asyncio.run(scenario())


def test_consecutive_llm_errors_stop_at_agent_threshold(tmp_path):
    fake = FakeLLM(
        lambda index, messages: LLMError("LLM_TIMEOUT", "temporary timeout", retryable=True)
    )
    runtime = AgentRuntime(
        Workspace(tmp_path),
        create_registry(Workspace(tmp_path)),
        fake,
        max_consecutive_llm_errors=2,
    )

    async def scenario():
        manager = TaskManager(runtime, mode="agent")
        task = manager.create("Stop after bounded retries")
        _ = [chunk async for chunk in manager.logs[task.id].stream()]
        assert manager.get(task.id).error.code == "CONSECUTIVE_LLM_ERRORS"
        assert len(fake.calls) == 2
        await manager.close()

    asyncio.run(scenario())


def test_consecutive_timeout_and_runtime_error_thresholds(tmp_path):
    class IndexArgs(ToolArgs):
        index: int

    async def command_timeout(arguments):
        return ToolResult(ok=False, error_code="COMMAND_TIMEOUT", error_message="timeout")

    async def infrastructure_error(arguments):
        return ToolResult(ok=False, error_code="IO_ERROR", error_message="I/O failed")

    async def run_case(handler, expected):
        registry = ToolRegistry([ToolSpec("probe", "Probe", IndexArgs, handler, implemented=True)])
        fake = FakeLLM(lambda index, messages: call(f"id-{index}", "probe", {"index": index}))
        runtime = AgentRuntime(
            Workspace(tmp_path),
            registry,
            fake,
            max_consecutive_command_timeouts=2,
            max_consecutive_runtime_errors=2,
        )
        manager = TaskManager(runtime, mode="agent")
        task = manager.create("Reach the failure threshold")
        _ = [chunk async for chunk in manager.logs[task.id].stream()]
        assert manager.get(task.id).error.code == expected
        assert len(fake.calls) == 2
        await manager.close()

    asyncio.run(run_case(command_timeout, "CONSECUTIVE_COMMAND_TIMEOUTS"))
    asyncio.run(run_case(infrastructure_error, "CONSECUTIVE_RUNTIME_ERRORS"))


def test_shutdown_waits_for_inflight_atomic_file_write(tmp_path, monkeypatch):
    from app.tools import files

    entered = threading.Event()
    release = threading.Event()
    real_commit = files.commit_text

    def delayed_commit(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(files, "commit_text", delayed_commit)
    fake = FakeLLM(
        lambda index, messages: call(
            "write-id", "write_file", {"path": "settled.txt", "content": "committed\n"}
        )
    )
    runtime = AgentRuntime(Workspace(tmp_path), create_registry(Workspace(tmp_path)), fake)

    async def scenario():
        manager = TaskManager(runtime, mode="agent")
        task = manager.create("Write during shutdown")
        assert await asyncio.to_thread(entered.wait, 2)
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0.05)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, timeout=5)

        finished = manager.get(task.id)
        assert finished.error.code == "SERVER_SHUTDOWN"
        assert (tmp_path / "settled.txt").read_text(encoding="utf-8") == "committed\n"
        events = decoded_events([chunk async for chunk in manager.logs[task.id].stream()])
        cancelled = [
            event
            for event in events
            if event["type"] == "tool_finished" and event["payload"].get("cancelled")
        ]
        assert len(cancelled) == 1
        assert events[-1]["type"] == "task_failed"

    asyncio.run(scenario())


def test_shutdown_waits_for_command_process_cleanup(tmp_path):
    (tmp_path / "wait.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        "Path('command.pid').write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    fake = FakeLLM(
        lambda index, messages: call("command-id", "run_command", {"command": "python wait.py"})
    )
    runtime = AgentRuntime(Workspace(tmp_path), create_registry(Workspace(tmp_path)), fake)

    async def scenario():
        manager = TaskManager(runtime, mode="agent")
        task = manager.create("Run until shutdown")
        for _attempt in range(250):
            if (tmp_path / "command.pid").exists():
                break
            await asyncio.sleep(0.02)
        assert (tmp_path / "command.pid").exists()
        pid = int((tmp_path / "command.pid").read_text(encoding="utf-8"))

        await asyncio.wait_for(manager.close(), timeout=8)
        assert manager.get(task.id).error.code == "SERVER_SHUTDOWN"
        for _attempt in range(100):
            if not process_running(pid):
                break
            await asyncio.sleep(0.02)
        assert not process_running(pid)
        events = decoded_events([chunk async for chunk in manager.logs[task.id].stream()])
        assert any(
            event["type"] == "tool_finished" and event["payload"].get("cancelled")
            for event in events
        )
        assert events[-1]["type"] == "task_failed"

    asyncio.run(scenario())
