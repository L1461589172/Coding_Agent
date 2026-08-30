import asyncio
import json
import threading

import pytest
from app.core.config import Settings
from app.history.errors import HistoryStorageUnavailable
from app.history.repository import JsonHistoryRepository
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


def test_workspace_switch_isolates_history_and_tracks_recent_paths(tmp_path, history_dir):
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()

    class ImmediateRunner:
        async def run(self, task, events):
            return f"done in {task.prompt}"

    settings = Settings(workspace=first_workspace, history_dir=history_dir)
    app = create_app(settings, runner=ImmediateRunner())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        initial = client.get("/api/workspaces").json()
        assert initial["current"]["path"] == str(first_workspace.resolve())
        assert initial["recent"] == [initial["current"]]

        first_task = client.post("/api/tasks", json={"prompt": "first workspace"}).json()
        assert client.get(f"/api/tasks/{first_task['id']}/events").status_code == 200

        switched = client.post("/api/workspaces/switch", json={"path": str(second_workspace)})
        assert switched.status_code == 200
        assert switched.json()["current"]["path"] == str(second_workspace.resolve())
        assert client.get("/api/meta").json()["workspace_path"] == str(second_workspace.resolve())
        assert client.get("/api/sessions").json()["items"] == []

        second_task = client.post("/api/tasks", json={"prompt": "second workspace"}).json()
        assert client.get(f"/api/tasks/{second_task['id']}/events").status_code == 200
        assert client.get(f"/api/tasks/{first_task['id']}").status_code == 404

        switched_back = client.post(
            "/api/workspaces/switch", json={"path": str(first_workspace)}
        ).json()
        assert [item["path"] for item in switched_back["recent"]] == [
            str(first_workspace.resolve()),
            str(second_workspace.resolve()),
        ]
        restored = client.get("/api/sessions").json()["items"]
        assert [item["id"] for item in restored] == [first_task["session_id"]]
        assert client.get(f"/api/tasks/{first_task['id']}").status_code == 200
        assert client.get(f"/api/tasks/{second_task['id']}").status_code == 404

        rejected = client.post("/api/workspaces/switch", json={"path": "relative/path"})
        assert rejected.status_code == 400
        assert client.get("/api/meta").json()["workspace_path"] == str(first_workspace.resolve())

    restarted = create_app(settings, runner=ImmediateRunner())
    with TestClient(restarted, base_url="http://127.0.0.1:8000") as client:
        recent = client.get("/api/workspaces").json()["recent"]
        assert [item["path"] for item in recent] == [
            str(first_workspace.resolve()),
            str(second_workspace.resolve()),
        ]


def test_failed_workspace_switch_restores_previous_workspace(tmp_path, history_dir, monkeypatch):
    first_workspace = tmp_path / "first"
    blocked_workspace = tmp_path / "blocked"
    first_workspace.mkdir()
    blocked_workspace.mkdir()
    original_open = JsonHistoryRepository.open

    async def fail_candidate(self):
        if self.workspace_root == blocked_workspace.resolve():
            raise HistoryStorageUnavailable("fixture failure")
        await original_open(self)

    monkeypatch.setattr(JsonHistoryRepository, "open", fail_candidate)
    app = create_app(Settings(workspace=first_workspace, history_dir=history_dir))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/workspaces/switch", json={"path": str(blocked_workspace)})
        assert response.status_code == 503
        assert "fixture" not in response.text
        assert client.get("/api/meta").json()["workspace_path"] == str(first_workspace.resolve())
        assert client.post("/api/tasks", json={"prompt": "still available"}).status_code == 202


def test_workspace_switch_rebinds_runtime_and_tools(tmp_path, history_dir):
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    (second_workspace / "marker.txt").write_text("second workspace", encoding="utf-8")
    app = create_app(Settings(workspace=first_workspace, history_dir=history_dir))

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/workspaces/switch", json={"path": str(second_workspace)})
        assert response.status_code == 200
        assert app.state.workspace.root == second_workspace.resolve()
        assert app.state.tasks.runner.workspace.root == second_workspace.resolve()
        result = asyncio.run(app.state.tools.execute("read_file", {"path": "marker.txt"}))
        assert result.ok
        assert result.output["content"] == "second workspace"


def test_workspace_switch_restores_after_current_history_close_error(
    tmp_path, history_dir, monkeypatch
):
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    original_close = JsonHistoryRepository.close
    failed_once = False

    async def fail_first_close(self):
        nonlocal failed_once
        await original_close(self)
        if self.workspace_root == first_workspace.resolve() and not failed_once:
            failed_once = True
            raise HistoryStorageUnavailable("fixture close failure")

    monkeypatch.setattr(JsonHistoryRepository, "close", fail_first_close)
    app = create_app(Settings(workspace=first_workspace, history_dir=history_dir))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/workspaces/switch", json={"path": str(second_workspace)})
        assert response.status_code == 503
        assert client.get("/api/meta").json()["workspace_path"] == str(first_workspace.resolve())
        assert client.post("/api/tasks", json={"prompt": "rollback works"}).status_code == 202


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
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
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
        switch = client.post("/api/workspaces/switch", json={"path": str(other_workspace)})
        assert switch.status_code == 409
        assert client.get("/api/meta").json()["workspace_path"] == str(tmp_path.resolve())
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
