import json

from app.agent.runtime import AgentRuntimeError
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def decode_sse(response) -> list[dict]:
    lines = response.text.splitlines()
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


class SuccessfulRunner:
    async def run(self, task, events):
        for number in range(4):
            await events.publish(
                task.id,
                "assistant_message",
                {"message": f"step {number}", "mode": "agent"},
                step=number + 1,
            )
        return "done"


def test_reconnect_replays_only_missing_events_and_agrees_with_task_state(tmp_path):
    app = create_app(Settings(workspace=tmp_path), runner=SuccessfulRunner())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "finish"}).json()
        full = decode_sse(client.get(f"/api/tasks/{task['id']}/events"))

        replay = decode_sse(client.get(f"/api/tasks/{task['id']}/events?after=2"))
        assert [event["id"] for event in replay] == ["3", "4", "5", "6"]
        assert replay == full[2:]
        assert full[-1]["type"] == "task_completed"
        assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "COMPLETED"
        assert client.get(f"/api/tasks/{task['id']}/events?after=6").status_code == 204


def test_large_specialized_payloads_are_bounded_and_terminal_event_is_retained(tmp_path):
    class LargePayloadRunner:
        async def run(self, task, events):
            common = {"call_id": "call-large", "tool": "write_file"}
            await events.publish(
                task.id,
                "tool_started",
                {**common, "arguments": {"path": "large.txt"}, "synthetic": False},
                step=1,
            )
            await events.publish(
                task.id,
                "tool_finished",
                {
                    **common,
                    "ok": True,
                    "error_code": None,
                    "error_message": None,
                    "truncated": True,
                    "duration_ms": 1.25,
                    "result": {
                        "ok": True,
                        "output": {"content": "x" * 20_000},
                        "error_code": None,
                        "error_message": None,
                        "truncated": True,
                    },
                    "synthetic": False,
                },
                step=1,
            )
            await events.publish(
                task.id,
                "file_changed",
                {
                    **common,
                    "path": "large.txt",
                    "action": "created",
                    "bytes_before": 0,
                    "bytes_after": 20_000,
                    "sha256_before": None,
                    "sha256_after": "a" * 64,
                    "diff": "+x\n" * 10_000,
                    "diff_truncated": True,
                    "cleanup_pending": False,
                },
                step=1,
            )
            await events.publish(
                task.id,
                "command_finished",
                {
                    "call_id": "command-large",
                    "ok": True,
                    "error_code": None,
                    "command": "python large.py",
                    "exit_code": 0,
                    "termination_reason": "exited",
                    "timed_out": False,
                    "cleanup_ok": True,
                    "stdout": "output\n" * 10_000,
                    "stderr": "",
                    "stdout_truncated": True,
                    "stderr_truncated": False,
                    "duration_ms": 2.5,
                },
                step=2,
            )
            return "large payload handled"

    app = create_app(
        Settings(
            workspace=tmp_path,
            event_max_payload_characters=512,
            event_max_history_characters=16_000,
            event_max_history_events=32,
        ),
        runner=LargePayloadRunner(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "large events"}).json()
        response = client.get(f"/api/tasks/{task['id']}/events")
        events = decode_sse(response)

        assert response.status_code == 200
        assert [event["type"] for event in events] == [
            "task_started",
            "tool_started",
            "tool_finished",
            "file_changed",
            "command_finished",
            "task_completed",
        ]
        for event in events[2:5]:
            assert event["payload"]["payload_truncated"] is True
            payload_text = json.dumps(event["payload"], ensure_ascii=False, separators=(",", ":"))
            assert len(payload_text) <= 512
        assert events[-1]["payload"] == {"result": "large payload handled"}
        assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "COMPLETED"


def test_failed_terminal_event_agrees_with_task_state(tmp_path):
    class FailingRunner:
        async def run(self, task, events):
            raise AgentRuntimeError("FIXTURE_FAILURE", "controlled failure")

    app = create_app(Settings(workspace=tmp_path), runner=FailingRunner())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "fail"}).json()
        events = decode_sse(client.get(f"/api/tasks/{task['id']}/events"))
        latest = client.get(f"/api/tasks/{task['id']}").json()

        assert events[-1]["type"] == "task_failed"
        assert events[-1]["payload"]["error"]["code"] == "FIXTURE_FAILURE"
        assert latest["status"] == "FAILED"
        assert latest["error"] == events[-1]["payload"]["error"]


def test_service_restart_does_not_claim_in_memory_task_can_be_restored(tmp_path):
    first_app = create_app(Settings(workspace=tmp_path), runner=SuccessfulRunner())
    with TestClient(first_app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "before restart"}).json()
        assert client.get(f"/api/tasks/{task['id']}/events").status_code == 200

    restarted_app = create_app(Settings(workspace=tmp_path), runner=SuccessfulRunner())
    with TestClient(restarted_app, base_url="http://127.0.0.1:8000") as client:
        assert client.get(f"/api/tasks/{task['id']}").status_code == 404
        assert client.get(f"/api/tasks/{task['id']}/events").status_code == 404
