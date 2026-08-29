import asyncio
import json
import threading

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_and_metadata_do_not_expose_settings(client):
    assert client.get("/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["agent_ready"] is False
    assert len(meta["tools"]) == 6
    assert meta["tool_statuses"] == {
        "list_files": "ready",
        "read_file": "ready",
        "search_text": "ready",
        "write_file": "ready",
        "replace_in_file": "ready",
        "run_command": "ready",
    }
    assert "fixture-secret" not in json.dumps(meta)
    assert "api_key" not in meta
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"prompt": ""},
        {"prompt": "  "},
        {"prompt": "x" * 8001},
        {"prompt": "x", "workspace": "elsewhere"},
    ],
)
def test_invalid_tasks(client, body):
    assert client.post("/api/tasks", json=body).status_code == 422


def test_task_lifecycle_and_sse_replay(client):
    response = client.post("/api/tasks", json={"prompt": "  修复测试  "})
    assert response.status_code == 202
    task = response.json()
    assert task["prompt"] == "修复测试"
    assert task["status"] == "PENDING"
    stream = client.get(f"/api/tasks/{task['id']}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")
    ]
    assert [e["type"] for e in events] == ["task_started", "assistant_message", "task_failed"]
    assert [e["id"] for e in events] == ["1", "2", "3"]
    result = client.get(f"/api/tasks/{task['id']}").json()
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "NOT_IMPLEMENTED"
    assert result["result"] is None
    assert result["started_at"] and result["finished_at"]
    replay = client.get(f"/api/tasks/{task['id']}/events", headers={"Last-Event-ID": "2"})
    assert replay.text.count("data: ") == 1
    assert "task_failed" in replay.text
    assert client.get(f"/api/tasks/{task['id']}/events?after=3").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}/events?after=4").status_code == 400
    assert client.get(f"/api/tasks/{task['id']}/events?after=-1").status_code == 400
    assert (
        client.get(f"/api/tasks/{task['id']}/events", headers={"Last-Event-ID": "bad"}).status_code
        == 400
    )
    assert client.post("/api/tasks", json={"prompt": "next"}).status_code == 202


def test_missing_task(client):
    assert client.get("/api/tasks/missing").status_code == 404
    assert client.get("/api/tasks/missing/events").status_code == 404


def test_origin_and_host_guards(client):
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/tasks", json={"prompt": "x"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/meta", headers={"Origin": "null"}).status_code == 403
    allowed = client.get("/api/meta", headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_active_task_conflict_and_shutdown(tmp_path, history_dir):
    started = threading.Event()
    stopped = threading.Event()

    class WaitingRunner:
        async def run(self, task, events):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    app = create_app(
        Settings(
            workspace=tmp_path,
            history_dir=history_dir,
        ),
        runner=WaitingRunner(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "wait"}).json()
        assert started.wait(timeout=2)
        assert client.post("/api/tasks", json={"prompt": "second"}).status_code == 409
        assert (
            client.post(
                f"/api/sessions/{task['session_id']}/tasks", json={"prompt": "follow up"}
            ).status_code
            == 409
        )
        assert client.delete(f"/api/sessions/{task['session_id']}").status_code == 409
    assert stopped.is_set()
    assert app.state.tasks.get(task["id"]).error.code == "SERVER_SHUTDOWN"


def test_unexpected_errors_are_not_exposed(tmp_path, history_dir):
    class BrokenRunner:
        async def run(self, task, events):
            raise RuntimeError("fixture-secret-must-not-leak")

    app = create_app(
        Settings(
            workspace=tmp_path,
            max_tasks=1,
            history_dir=history_dir,
        ),
        runner=BrokenRunner(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        task = client.post("/api/tasks", json={"prompt": "x"}).json()
        result = client.get(f"/api/tasks/{task['id']}/events")
        assert "RUNTIME_ERROR" in result.text
        assert "fixture-secret" not in result.text
        assert client.post("/api/tasks", json={"prompt": "next"}).status_code == 202
