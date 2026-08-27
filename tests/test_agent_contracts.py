import asyncio

import pytest
from app.agent.context import Conversation
from app.agent.stop import StopController
from app.core.config import Settings
from app.tools.registry import create_registry
from app.tools.workspace import Workspace


def test_config_does_not_repr_secret(tmp_path):
    settings = Settings(workspace=tmp_path, api_key="do-not-show-this")
    assert "do-not-show-this" not in repr(settings)
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, max_steps=0)


def test_repeat_and_step_limit():
    stop = StopController(max_steps=2)
    assert not stop.reached_step_limit(1)
    assert stop.reached_step_limit(2)
    assert [stop.observe("read", {"path": "a"}) for _ in range(4)] == [
        "continue",
        "continue",
        "warn",
        "stop",
    ]
    assert stop.observe("read", {"path": "b"}) == "continue"


def test_context_preserves_call_result_pairs():
    conversation = Conversation("system", "original task")
    conversation.append_round([{"role": "assistant", "content": "first"}])
    pair = [
        {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "result"},
    ]
    conversation.append_round(pair)
    context = conversation.build_context(recent_rounds=1)
    assert len(context) == 4
    assert context[1]["content"] == "original task"
    assert context[2:] == pair
    context[0]["content"] = "mutated"
    assert conversation.build_context()[0]["content"] == "system"
    with pytest.raises(ValueError):
        conversation.append_round(pair[:1])


def test_tool_registry_validation_and_execution(tmp_path):
    async def scenario():
        registry = create_registry(Workspace(tmp_path))
        assert len(registry.schemas()) == 6
        assert (await registry.execute("missing", {})).error_code == "UNKNOWN_TOOL"
        assert (await registry.execute("read_file", {})).error_code == "INVALID_ARGUMENTS"
        assert (
            await registry.execute(
                "run_command",
                {
                    "command": "anything",
                    "timeout_seconds": "30",
                },
            )
        ).error_code == "INVALID_ARGUMENTS"
        inputs = {
            "write_file": {"path": "a.txt", "content": "hello"},
            "replace_in_file": {"path": "a.txt", "old_text": "hello", "new_text": "bye"},
            "run_command": {"command": "echo hello"},
        }
        for name, args in inputs.items():
            result = await registry.execute(name, args)
            assert result.ok, result
        assert (tmp_path / "a.txt").read_text() == "bye"
        assert set(registry.availability().values()) == {"ready"}

    asyncio.run(scenario())
