import asyncio

from app.agent.runtime import AgentRuntimeError
from app.core.config import Settings
from app.core.events import EventLimits, EventLog
from app.main import create_app
from app.services.tasks import TaskManager
from app.services.trace import ExecutionTrace, TraceRecorder
from fastapi.testclient import TestClient


def _command_payload(command: str, *, ok: bool, exit_code: int) -> dict:
    return {
        "call_id": f"command-{command}",
        "ok": ok,
        "error_code": None if ok else "COMMAND_FAILED",
        "command": command,
        "exit_code": exit_code,
        "termination_reason": "exited",
        "timed_out": False,
        "cleanup_ok": True,
        "stdout": "2 passed\n" if ok else "1 failed\n",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "duration_ms": 12.5,
    }


def test_summary_uses_complete_trace_after_event_payload_and_history_eviction():
    class Runner:
        async def run(self, task, events):
            await events.publish(
                task.id,
                "assistant_message",
                {"message": "Inspecting", "mode": "agent"},
                step=1,
            )
            await events.publish(
                task.id,
                "tool_started",
                {
                    "call_id": "read-1",
                    "tool": "read_file",
                    "arguments": {"path": "src/example.py"},
                    "synthetic": False,
                },
                step=1,
            )
            await events.publish(
                task.id,
                "tool_started",
                {
                    "call_id": "read-1",
                    "tool": "read_file",
                    "arguments": {"path": "src/example.py"},
                    "synthetic": False,
                },
                step=1,
            )
            await events.publish(
                task.id,
                "tool_finished",
                {
                    "call_id": "read-1",
                    "tool": "read_file",
                    "ok": True,
                    "error_code": None,
                    "error_message": None,
                    "truncated": False,
                    "duration_ms": 1.0,
                    "result": {
                        "ok": True,
                        "output": {"path": "src/example.py", "content": "x" * 1000},
                        "error_code": None,
                        "error_message": None,
                        "truncated": False,
                    },
                    "synthetic": False,
                },
                step=1,
            )
            await events.publish(
                task.id,
                "file_changed",
                {"call_id": "write-1", "path": "src/example.py"},
                step=2,
            )
            await events.publish(
                task.id,
                "command_finished",
                _command_payload("python -m pytest tests/test_example.py", ok=True, exit_code=0),
                step=3,
            )
            for number in range(5):
                await events.publish(
                    task.id,
                    "assistant_message",
                    {"message": f"progress-{number}", "mode": "recovery"},
                    step=3,
                )
            return "done"

    async def scenario():
        manager = TaskManager(
            Runner(),
            mode="agent",
            event_limits=EventLimits(
                max_payload_characters=256,
                max_history_characters=3000,
                max_history_events=3,
            ),
        )
        created = await manager.create("summarize")
        _ = [chunk async for chunk in manager.get_log(created.id).stream()]
        task = manager.get(created.id)
        assert task.summary is not None
        assert task.summary.files_read == ["src/example.py"]
        assert task.summary.files_changed == ["src/example.py"]
        assert task.summary.tool_calls == 1
        assert task.summary.decision_steps == 1
        assert task.summary.verification is not None
        assert task.summary.verification.passed is True
        assert task.summary.verification.command == "python -m pytest tests/test_example.py"
        assert task.summary.duration_ms is not None
        assert manager.get_log(created.id).first_id > 1
        await manager.close()

    asyncio.run(scenario())


def test_last_recognized_pytest_command_and_failure_code_win():
    class Runner:
        async def run(self, task, events):
            await events.publish(
                task.id,
                "command_finished",
                _command_payload("pytest tests/test_one.py", ok=True, exit_code=0),
            )
            await events.publish(
                task.id,
                "command_finished",
                _command_payload("echo pytest", ok=True, exit_code=0),
            )
            await events.publish(
                task.id,
                "command_finished",
                _command_payload("python3 -m pytest tests/test_two.py", ok=False, exit_code=1),
            )
            raise AgentRuntimeError("FIXTURE_FAILURE", "fixture failed")

    async def scenario():
        manager = TaskManager(Runner(), mode="agent")
        created = await manager.create("fail after verification")
        _ = [chunk async for chunk in manager.get_log(created.id).stream()]
        task = manager.get(created.id)
        assert task.summary is not None
        assert task.summary.verification is not None
        assert task.summary.verification.command == "python3 -m pytest tests/test_two.py"
        assert task.summary.verification.passed is False
        assert task.summary.error_codes == ["COMMAND_FAILED", "FIXTURE_FAILURE"]
        await manager.close()

    asyncio.run(scenario())


def test_trace_does_not_record_an_event_rejected_by_event_log():
    async def scenario():
        log = EventLog()
        trace = ExecutionTrace()
        recorder = TraceRecorder(log, trace)
        await log.publish("task", "task_completed", {"result": "done"})
        try:
            await recorder.publish(
                "task",
                "tool_started",
                {"call_id": "late", "tool": "read_file"},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Publishing after a terminal event must fail")
        assert trace.tool_calls == 0

    asyncio.run(scenario())


def test_immediate_shutdown_has_terminal_partial_summary():
    class UnusedRunner:
        async def run(self, task, events):
            raise AssertionError("runner must not start")

    async def scenario():
        manager = TaskManager(UnusedRunner())
        created = await manager.create("pending")
        await manager.close()
        task = manager.get(created.id)
        assert task.summary is not None
        assert task.summary.error_codes == ["SERVER_SHUTDOWN"]
        assert task.summary.duration_ms is None

    asyncio.run(scenario())


def test_task_api_summary_is_null_before_terminal_and_complete_after_terminal(
    tmp_path, history_dir
):
    class Runner:
        async def run(self, task, events):
            await events.publish(
                task.id,
                "file_changed",
                {"call_id": "edit", "tool": "replace_in_file", "path": "calculator.py"},
            )
            await events.publish(
                task.id,
                "command_finished",
                _command_payload("pytest -q", ok=True, exit_code=0),
            )
            return "done"

    app = create_app(
        Settings(
            workspace=tmp_path,
            history_dir=history_dir,
        ),
        runner=Runner(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        created = client.post("/api/tasks", json={"prompt": "finish"}).json()
        assert created["summary"] is None
        response = client.get(f"/api/tasks/{created['id']}/events")
        assert response.status_code == 200
        latest = client.get(f"/api/tasks/{created['id']}").json()

        assert latest["status"] == "COMPLETED"
        assert latest["summary"]["files_changed"] == ["calculator.py"]
        assert latest["summary"]["verification"]["passed"] is True


def test_trace_collections_and_strings_are_bounded():
    trace = ExecutionTrace()
    for number in range(140):
        trace.observe("file_changed", {"path": f"path-{number}" + "x" * 1200})
    for number in range(70):
        payload = _command_payload(f"pytest test_{number}.py" + "x" * 5000, ok=True, exit_code=0)
        payload["stdout"] = "o" * 3000
        trace.observe("command_finished", payload)
    trace.observe(
        "tool_finished",
        {"tool": "read_file", "ok": False, "error_code": "E" * 300},
    )

    assert len(trace.files_changed) == 128
    assert all(len(path) <= 1000 for path in trace.files_changed)
    assert len(trace.commands) == 64
    assert all(len(command.command) <= 4000 for command in trace.commands)
    assert all(len(command.stdout) <= 2000 for command in trace.commands)
    assert trace.error_codes == ["E" * 128]
