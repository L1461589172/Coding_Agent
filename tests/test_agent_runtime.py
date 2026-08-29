import asyncio
import json
from copy import deepcopy

from app.agent.context import ContextBudget, measure_model_input
from app.agent.llm import ModelReply, OpenAICompatibleLLMClient, ToolCall
from app.agent.runtime import AgentRuntime, AgentRuntimeError
from app.core.config import Settings
from app.core.events import EventLog
from app.main import create_app
from app.models.task import Task
from app.services.tasks import TaskManager
from app.tools.base import ToolArgs, ToolResult, ToolSpec
from app.tools.registry import ToolRegistry, create_registry
from app.tools.workspace import Workspace
from fastapi.testclient import TestClient


class FakeLLM:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []
        self.closed = False

    async def complete(self, messages, tools):
        self.calls.append((deepcopy(messages), deepcopy(tools)))
        index = len(self.calls) - 1
        reply = self.replies(index, messages) if callable(self.replies) else self.replies[index]
        return reply.model_copy(deep=True)

    async def close(self):
        self.closed = True


def call(call_id: str, name: str, arguments: dict) -> ModelReply:
    return ModelReply(tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def tool_message(messages, call_id):
    return next(
        message
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id") == call_id
    )


def test_agent_loop_reads_edits_runs_test_and_returns_final_reply(tmp_path):
    (tmp_path / "calculator.py").write_text(
        "def add(left, right):\n    return left - right\n", encoding="utf-8"
    )
    (tmp_path / "test_calculator.py").write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    registry = create_registry(Workspace(tmp_path))
    replies = [
        call("read-1", "read_file", {"path": "calculator.py"}),
        call(
            "edit-1",
            "replace_in_file",
            {
                "path": "calculator.py",
                "old_text": "return left - right",
                "new_text": "return left + right",
            },
        ),
        call(
            "test-1",
            "run_command",
            {"command": "python -m pytest test_calculator.py -q", "timeout_seconds": 15},
        ),
        ModelReply(content="Fixed add and verified the focused pytest test passes."),
    ]
    fake = FakeLLM(replies)
    runtime = AgentRuntime(Workspace(tmp_path), registry, fake, max_steps=8)

    async def scenario():
        result = await runtime.run(Task(prompt="Fix add and run its test"), EventLog())
        assert result == replies[-1].content
        assert len(fake.calls) == 4
        assert all(schemas == registry.schemas() for _, schemas in fake.calls)

        read_result = json.loads(tool_message(fake.calls[1][0], "read-1")["content"])
        edit_result = json.loads(tool_message(fake.calls[2][0], "edit-1")["content"])
        command_result = json.loads(tool_message(fake.calls[3][0], "test-1")["content"])
        assert read_result["ok"] and "left - right" in read_result["output"]["content"]
        assert edit_result["ok"] and edit_result["output"]["action"] == "updated"
        assert command_result["ok"] and command_result["output"]["exit_code"] == 0
        assert (
            (tmp_path / "calculator.py")
            .read_text(encoding="utf-8")
            .endswith("return left + right\n")
        )
        await runtime.close()
        assert fake.closed

    asyncio.run(scenario())


def test_parallel_tool_results_are_returned_in_call_id_order(tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    registry = create_registry(Workspace(tmp_path))
    fake = FakeLLM(
        [
            ModelReply(
                tool_calls=[
                    ToolCall(id="list-id", name="list_files", arguments={}),
                    ToolCall(id="read-id", name="read_file", arguments={"path": "note.txt"}),
                ]
            ),
            ModelReply(content="Both observations received."),
        ]
    )
    runtime = AgentRuntime(Workspace(tmp_path), registry, fake)

    async def scenario():
        assert await runtime.run(Task(prompt="Inspect files"), EventLog()) == (
            "Both observations received."
        )
        messages = fake.calls[1][0]
        tool_messages = [message for message in messages if message["role"] == "tool"]
        assert [message["tool_call_id"] for message in tool_messages[-2:]] == [
            "list-id",
            "read-id",
        ]
        assert all(json.loads(message["content"])["ok"] for message in tool_messages[-2:])

    asyncio.run(scenario())


def test_invalid_tool_arguments_are_observed_and_model_can_recover(tmp_path):
    registry = create_registry(Workspace(tmp_path))
    fake = FakeLLM(
        [
            call("bad-read", "read_file", {}),
            ModelReply(content="The read arguments were invalid; no file was changed."),
        ]
    )
    runtime = AgentRuntime(Workspace(tmp_path), registry, fake)

    async def scenario():
        result = await runtime.run(Task(prompt="Read without a path"), EventLog())
        observation = json.loads(tool_message(fake.calls[1][0], "bad-read")["content"])
        assert result.startswith("The read arguments")
        assert observation["ok"] is False
        assert observation["error_code"] == "INVALID_ARGUMENTS"

    asyncio.run(scenario())


def test_runtime_applies_tool_result_context_trimming(tmp_path):
    class EmptyArgs(ToolArgs):
        pass

    async def large_result(arguments):
        return ToolResult(ok=True, output={"content": "x" * 10_000})

    registry = ToolRegistry(
        [ToolSpec("large", "Return a large fixture", EmptyArgs, large_result, implemented=True)]
    )

    def replies(index, messages):
        if index == 0:
            return call("large-id", "large", {})
        observation = tool_message(messages, "large-id")
        payload = json.loads(observation["content"])
        assert len(observation["content"]) <= 400
        assert payload["context_truncated"] is True
        assert measure_model_input(messages, registry.schemas()).characters <= 2_000
        return ModelReply(content="Large result was safely summarized for context.")

    fake = FakeLLM(replies)
    runtime = AgentRuntime(
        Workspace(tmp_path),
        registry,
        fake,
        context_budget=ContextBudget(
            max_characters=2_000,
            max_tokens=2_000,
            max_tool_result_characters=400,
        ),
    )
    asyncio.run(runtime.run(Task(prompt="Get the large result"), EventLog()))


def test_repeat_warning_prevents_third_execution_and_fourth_call_stops(tmp_path):
    class EmptyArgs(ToolArgs):
        pass

    executions = 0

    async def probe(arguments):
        nonlocal executions
        executions += 1
        return ToolResult(ok=True, output={"execution": executions})

    registry = ToolRegistry([ToolSpec("probe", "Probe", EmptyArgs, probe, implemented=True)])

    def repeated(index, messages):
        return call(f"repeat-{index}", "probe", {})

    fake = FakeLLM(repeated)
    runtime = AgentRuntime(Workspace(tmp_path), registry, fake, max_steps=10)

    async def scenario():
        try:
            await runtime.run(Task(prompt="Repeat"), EventLog())
        except AgentRuntimeError as error:
            assert error.code == "REPEATED_TOOL_CALL"
        else:
            raise AssertionError("Repeated calls should stop the loop")
        assert len(fake.calls) == 4
        assert executions == 2
        warning = json.loads(tool_message(fake.calls[3][0], "repeat-2")["content"])
        assert warning["error_code"] == "REPEATED_TOOL_CALL"

    asyncio.run(scenario())


def test_step_limit_is_a_structured_task_failure(tmp_path):
    class EmptyArgs(ToolArgs):
        pass

    async def probe(arguments):
        return ToolResult(ok=True)

    registry = ToolRegistry([ToolSpec("probe", "Probe", EmptyArgs, probe, implemented=True)])
    fake = FakeLLM(lambda index, messages: call(f"step-{index}", "probe", {"extra": index}))
    runtime = AgentRuntime(Workspace(tmp_path), registry, fake, max_steps=2)

    async def scenario():
        manager = TaskManager(runtime, mode="agent")
        task = await manager.create("Never finish")
        chunks = [chunk async for chunk in manager.get_log(task.id).stream()]
        finished = manager.get(task.id)
        assert finished.mode == "agent"
        assert finished.error.code == "AGENT_STEP_LIMIT"
        assert "AGENT_STEP_LIMIT" in chunks[-1]
        assert len(fake.calls) == 2
        await manager.close()

    asyncio.run(scenario())


def test_configured_app_uses_agent_runtime_and_closes_model(tmp_path, history_dir, monkeypatch):
    fake = FakeLLM([ModelReply(content="Configured runtime completed.")])
    monkeypatch.setattr(
        OpenAICompatibleLLMClient,
        "from_settings",
        classmethod(lambda cls, settings: fake),
    )
    app = create_app(
        Settings(
            workspace=tmp_path,
            history_dir=history_dir,
            api_key="fixture-key",
            base_url="https://model.example/v1",
            model="fixture-model",
        )
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health").json()["agent_ready"] is True
        assert client.get("/api/meta").json()["mode"] == "agent"
        task = client.post("/api/tasks", json={"prompt": "Finish immediately"}).json()
        events = client.get(f"/api/tasks/{task['id']}/events")
        assert "task_completed" in events.text
        finished = client.get(f"/api/tasks/{task['id']}").json()
        assert finished["status"] == "COMPLETED"
        assert finished["mode"] == "agent"
    assert fake.closed
