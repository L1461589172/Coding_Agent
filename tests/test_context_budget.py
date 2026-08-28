import json

import pytest
from app.agent.context import (
    ContextBudget,
    ContextBudgetError,
    Conversation,
    estimate_tokens,
    measure_context,
    measure_model_input,
)


def round_messages(call_id: str, content: str, assistant_text: str = ""):
    return [
        {
            "role": "assistant",
            "content": assistant_text,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


def test_token_estimator_and_context_measurement_are_deterministic():
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("中文ab") == 3
    messages = [{"role": "user", "content": "中文 and ascii"}]
    first = measure_context(messages)
    assert first == measure_context(messages)
    assert first.characters > len(messages[0]["content"])
    assert first.tokens > 0


def test_context_keeps_newest_complete_rounds_within_character_budget():
    conversation = Conversation("system", "task")
    for number in range(3):
        conversation.append_round(round_messages(f"call-{number}", f"result-{number}" * 10))

    base = conversation.base
    newest_two = base + [message for item in conversation.rounds[-2:] for message in item]
    all_rounds = base + [message for item in conversation.rounds for message in item]
    newest_size = measure_context(newest_two)
    assert measure_context(all_rounds).characters > newest_size.characters

    context = conversation.build_context(
        budget=ContextBudget(
            max_characters=newest_size.characters,
            max_tokens=10_000,
            max_tool_result_characters=1_000,
        )
    )
    assert [message.get("tool_call_id") for message in context if message["role"] == "tool"] == [
        "call-1",
        "call-2",
    ]
    assert measure_context(context).characters <= newest_size.characters


def test_token_budget_can_drop_old_round_without_splitting_pair():
    conversation = Conversation("system", "task")
    conversation.append_round(round_messages("old", "a" * 80))
    conversation.append_round(round_messages("new", "b" * 80))
    newest = conversation.base + conversation.rounds[-1]
    newest_tokens = measure_context(newest).tokens

    context = conversation.build_context(
        budget=ContextBudget(
            max_characters=10_000,
            max_tokens=newest_tokens,
            max_tool_result_characters=1_000,
        )
    )
    assert [message.get("tool_call_id") for message in context if message["role"] == "tool"] == [
        "new"
    ]


def test_large_tool_result_is_context_trimmed_as_valid_json_only_when_built():
    raw_result = json.dumps(
        {
            "ok": True,
            "output": {"content": "x" * 5_000},
            "error_code": None,
            "error_message": None,
            "truncated": False,
        }
    )
    conversation = Conversation(
        "system",
        "task",
        ContextBudget(
            max_characters=2_000,
            max_tokens=2_000,
            max_tool_result_characters=400,
        ),
    )
    conversation.append_round(round_messages("large", raw_result))
    context = conversation.build_context()
    tool_message = context[-1]
    trimmed = json.loads(tool_message["content"])

    assert tool_message["tool_call_id"] == "large"
    assert len(tool_message["content"]) <= 400
    assert trimmed["context_truncated"] is True
    assert trimmed["original_characters"] == len(raw_result)
    assert trimmed["ok"] is True
    assert conversation.rounds[0][1]["content"] == raw_result
    assert measure_context(context).characters <= 2_000


def test_base_and_unshrinkable_latest_round_fail_explicitly():
    with pytest.raises(ContextBudgetError, match="original task"):
        Conversation(
            "system",
            "task too large",
            ContextBudget(
                max_characters=20,
                max_tokens=20,
                max_tool_result_characters=256,
            ),
        ).build_context()

    conversation = Conversation(
        "system",
        "task",
        ContextBudget(
            max_characters=700,
            max_tokens=700,
            max_tool_result_characters=256,
        ),
    )
    conversation.append_round(round_messages("huge", "{}", assistant_text="x" * 2_000))
    with pytest.raises(ContextBudgetError, match="Latest complete round"):
        conversation.build_context()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "large_schema",
                "description": "x" * 1_000,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    base_only = Conversation(
        "system",
        "task",
        ContextBudget(
            max_characters=500,
            max_tokens=500,
            max_tool_result_characters=256,
        ),
    )
    assert measure_model_input(base_only.base, tools).characters > 500
    with pytest.raises(ContextBudgetError, match="original task"):
        base_only.build_context(tools=tools)


def test_conversation_rejects_malformed_or_unpaired_calls():
    conversation = Conversation("system", "task")
    with pytest.raises(ValueError, match="string ids"):
        conversation.append_round([{"role": "assistant", "tool_calls": [{"type": "function"}]}])
    with pytest.raises(ValueError, match="exactly one"):
        conversation.append_round(
            [
                {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
                {"role": "tool", "tool_call_id": "different", "content": "result"},
            ]
        )
