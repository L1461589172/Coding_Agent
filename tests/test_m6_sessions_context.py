import asyncio
from pathlib import Path

import pytest
from app.agent.context import ContextBudget, Conversation, measure_model_input
from app.core.events import EventLimits
from app.history.context import build_task_recap
from app.history.errors import HistoryCapacity
from app.history.repository import InMemoryHistoryRepository, JsonHistoryRepository
from app.models.task import Task
from app.services.tasks import TaskManager
from app.services.trace import ExecutionTrace


class CompletingRunner:
    def __init__(self) -> None:
        self.received = []

    async def run(self, task, events):
        self.received.append(task)
        return f"completed: {task.prompt}"

    async def close(self):
        return None


async def _wait_terminal(manager: TaskManager, task_id: str):
    for _ in range(100):
        task = manager.get(task_id)
        if task.status.value in {"COMPLETED", "FAILED"}:
            return task
        await asyncio.sleep(0.01)
    raise AssertionError("Task did not become terminal")


def test_session_api_follow_up_pagination_and_delete(client):
    first_response = client.post("/api/tasks", json={"prompt": "first round"})
    assert first_response.status_code == 202
    first = first_response.json()
    assert first["session_id"]
    assert first["ordinal"] == 1
    assert client.get(f"/api/tasks/{first['id']}/events").status_code == 200

    sessions = client.get("/api/sessions?limit=1").json()
    assert sessions["items"][0]["id"] == first["session_id"]
    assert client.get(f"/api/sessions/{first['session_id']}").status_code == 200
    assert client.get("/api/sessions?before=damaged").status_code == 400

    follow_response = client.post(
        f"/api/sessions/{first['session_id']}/tasks",
        json={"prompt": "continue it"},
    )
    assert follow_response.status_code == 202
    follow = follow_response.json()
    assert follow["session_id"] == first["session_id"]
    assert follow["ordinal"] == 2
    assert client.get(f"/api/tasks/{follow['id']}/events").status_code == 200

    page = client.get(f"/api/sessions/{first['session_id']}/tasks?limit=1").json()
    assert [task["ordinal"] for task in page["items"]] == [2]
    assert page["next_before_ordinal"] == 2
    older = client.get(f"/api/sessions/{first['session_id']}/tasks?limit=1&before_ordinal=2").json()
    assert [task["ordinal"] for task in older["items"]] == [1]

    assert client.delete(f"/api/sessions/{first['session_id']}").status_code == 204
    assert client.get(f"/api/sessions/{first['session_id']}").status_code == 404
    assert client.get(f"/api/tasks/{first['id']}").status_code == 404
    assert client.delete(f"/api/sessions/{first['session_id']}").status_code == 404


def test_follow_up_receives_deterministic_recap_without_raw_execution_fields():
    async def scenario():
        repository = InMemoryHistoryRepository()
        runner = CompletingRunner()
        manager = TaskManager(runner, repository=repository, mode="agent")
        try:
            first = await manager.create("change the greeting")
            await _wait_terminal(manager, first.id)
            recap = build_task_recap(repository.get_persisted_task(first.id))
            assert recap is not None
            assert set(recap.model_dump()) == {
                "task_id",
                "ordinal",
                "status",
                "user_prompt",
                "assistant_result",
                "error_code",
                "files_changed",
                "verification",
            }

            follow = await manager.create("now verify it", first.session_id)
            await _wait_terminal(manager, follow.id)
            received = runner.received[-1]
            serialized = str(received.history_rounds)
            assert received.history_task_count == 1
            assert "change the greeting" in serialized
            for forbidden in ("tool_result", "stdout", "stderr", "diff", "call_id"):
                assert forbidden not in serialized
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_session_context_uses_complete_recent_rounds_with_existing_total_budget():
    rounds = [
        [
            {"role": "user", "content": f"old request {index} " + "x" * 200},
            {"role": "assistant", "content": f"recap {index} " + "y" * 200},
        ]
        for index in range(8)
    ]
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    budget = ContextBudget(max_characters=1_500, max_tokens=1_500, max_tool_result_characters=256)
    conversation = Conversation("system", "current prompt", budget, history_rounds=rounds)
    messages = conversation.build_context(tools=tools)
    size = measure_model_input(messages, tools)
    assert size.characters <= budget.max_characters
    assert size.tokens <= budget.max_tokens
    assert 0 < conversation.included_history_tasks < len(rounds)
    assert conversation.omitted_history_tasks + conversation.included_history_tasks == len(rounds)
    history_users = [item["content"] for item in messages if item["role"] == "user"][:-1]
    assert history_users == sorted(history_users, key=lambda value: int(value.split()[2]))
    assert messages[-1]["content"] == "current prompt"


def test_json_history_byte_limit(tmp_path, history_dir):
    async def scenario():
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        repository = JsonHistoryRepository(
            history_dir,
            workspace,
            EventLimits(),
            max_bytes=1,
        )
        await repository.open()
        runner = CompletingRunner()
        manager = TaskManager(runner, repository=repository, mode="agent")
        try:
            with pytest.raises(HistoryCapacity):
                await repository.create_with_task(
                    Task(prompt="too large"),
                    ExecutionTrace(),
                )
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_model_configuration_canary_is_not_persisted(client, history_dir: Path):
    response = client.post("/api/tasks", json={"prompt": "safe prompt"})
    task = response.json()
    client.get(f"/api/tasks/{task['id']}/events")
    stored = "\n".join(
        path.read_text("utf-8", errors="ignore")
        for path in history_dir.rglob("*.json")
        if path.is_file()
    )
    assert "fixture-secret-must-not-leak" not in stored
