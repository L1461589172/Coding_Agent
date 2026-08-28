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
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, llm_timeout_seconds=0)
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, llm_max_retries=11)
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, llm_timeout_seconds=float("nan"))
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, context_max_characters=0)
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, context_max_tokens=0)
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, tool_result_max_characters=255)
    with pytest.raises(ValueError):
        Settings(workspace=tmp_path, context_recent_rounds=0)
    assert not Settings(
        workspace=tmp_path,
        api_key=" ",
        base_url="https://model.example/v1",
        model="fixture-model",
    ).model_configured


def test_model_policy_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CODING_AGENT_API_KEY", "environment-secret")
    monkeypatch.setenv("CODING_AGENT_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("CODING_AGENT_MODEL", "test-model")
    monkeypatch.setenv("CODING_AGENT_LLM_TIMEOUT_SECONDS", "45.5")
    monkeypatch.setenv("CODING_AGENT_LLM_CONNECT_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("CODING_AGENT_LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("CODING_AGENT_CONTEXT_MAX_CHARACTERS", "60000")
    monkeypatch.setenv("CODING_AGENT_CONTEXT_MAX_TOKENS", "15000")
    monkeypatch.setenv("CODING_AGENT_TOOL_RESULT_MAX_CHARACTERS", "9000")
    monkeypatch.setenv("CODING_AGENT_CONTEXT_RECENT_ROUNDS", "6")
    settings = Settings.from_env(str(tmp_path))
    assert settings.base_url == "https://model.example/v1"
    assert settings.model == "test-model"
    assert settings.llm_timeout_seconds == 45.5
    assert settings.llm_connect_timeout_seconds == 7.5
    assert settings.llm_max_retries == 3
    assert settings.context_max_characters == 60_000
    assert settings.context_max_tokens == 15_000
    assert settings.tool_result_max_characters == 9_000
    assert settings.context_recent_rounds == 6
    assert settings.model_configured
    assert "environment-secret" not in repr(settings)


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
