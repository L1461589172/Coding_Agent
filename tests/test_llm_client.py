import asyncio
import json

import httpx
import pytest
from app.agent.llm import LLMError, OpenAICompatibleLLMClient
from app.core.config import Settings
from app.tools.registry import create_registry
from app.tools.workspace import Workspace


def run(coroutine):
    return asyncio.run(coroutine)


def text_response(content: str = "done") -> dict:
    return {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def tool_response(
    *,
    call_id: str = "call-1",
    name: str = "read_file",
    arguments: str = '{"path":"README.md"}',
) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def make_adapter(handler, **kwargs):
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs.setdefault("retry_base_seconds", 0)
    adapter = OpenAICompatibleLLMClient(
        api_key="fixture-secret-key",
        base_url="https://model.example/v1/",
        model="fixture-model",
        client=http_client,
        **kwargs,
    )
    return adapter, http_client


def test_sends_registry_schemas_and_parses_text(tmp_path):
    schemas = create_registry(Workspace(tmp_path)).schemas()

    async def scenario():
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://model.example/v1/chat/completions"
            assert request.headers["Authorization"] == "Bearer fixture-secret-key"
            payload = json.loads(request.content)
            assert payload == {
                "model": "fixture-model",
                "messages": [{"role": "user", "content": "fix it"}],
                "stream": False,
                "tools": schemas,
                "tool_choice": "auto",
            }
            return httpx.Response(200, json=text_response("finished"))

        adapter, http_client = make_adapter(handler)
        try:
            reply = await adapter.complete([{"role": "user", "content": "fix it"}], schemas)
            assert reply.content == "finished"
            assert reply.tool_calls == []
        finally:
            await adapter.close()
            assert not http_client.is_closed
            await http_client.aclose()

    run(scenario())


def test_parses_native_tool_call(tmp_path):
    schemas = create_registry(Workspace(tmp_path)).schemas()

    async def scenario():
        adapter, http_client = make_adapter(
            lambda request: httpx.Response(200, json=tool_response())
        )
        try:
            reply = await adapter.complete([], schemas)
            assert reply.content == ""
            assert reply.tool_calls[0].model_dump() == {
                "id": "call-1",
                "name": "read_file",
                "arguments": {"path": "README.md"},
            }
        finally:
            await http_client.aclose()

    run(scenario())


def test_from_settings_applies_model_policy(tmp_path):
    requests = 0

    async def scenario():
        nonlocal requests

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            assert request.extensions["timeout"] == {
                "connect": 3.0,
                "read": 12.0,
                "write": 12.0,
                "pool": 12.0,
            }
            if requests == 1:
                return httpx.Response(429)
            return httpx.Response(200, json=text_response())

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        settings = Settings(
            workspace=tmp_path,
            api_key="settings-key",
            base_url="https://settings.example/v1",
            model="settings-model",
            llm_timeout_seconds=12,
            llm_connect_timeout_seconds=3,
            llm_max_retries=1,
        )
        adapter = OpenAICompatibleLLMClient.from_settings(
            settings, client=http_client, sleep=lambda delay: asyncio.sleep(0)
        )
        try:
            assert (await adapter.complete([], [])).content == "done"
            assert requests == 2
        finally:
            await http_client.aclose()

    run(scenario())


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (None, "LLM_INVALID_RESPONSE"),
        ({"choices": []}, "LLM_INVALID_RESPONSE"),
        (
            {"choices": text_response()["choices"] * 2},
            "LLM_INVALID_RESPONSE",
        ),
        (
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "user", "content": "wrong role"},
                    }
                ]
            },
            "LLM_INVALID_RESPONSE",
        ),
        (text_response("   "), "LLM_INVALID_RESPONSE"),
        (tool_response(arguments="not json"), "LLM_INVALID_RESPONSE"),
        (tool_response(arguments="[]"), "LLM_INVALID_RESPONSE"),
        (tool_response(name="invented_tool"), "LLM_UNKNOWN_TOOL"),
    ],
)
def test_rejects_invalid_responses_without_retry(tmp_path, body, code):
    calls = 0
    schemas = create_registry(Workspace(tmp_path)).schemas()

    async def scenario():
        nonlocal calls

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if body is None:
                return httpx.Response(200, content=b"not-json")
            return httpx.Response(200, json=body)

        adapter, http_client = make_adapter(handler, max_retries=2)
        try:
            with pytest.raises(LLMError) as captured:
                await adapter.complete([], schemas)
            assert captured.value.code == code
            assert calls == 1
        finally:
            await http_client.aclose()

    run(scenario())


def test_rejects_duplicate_tool_call_ids(tmp_path):
    schemas = create_registry(Workspace(tmp_path)).schemas()
    body = tool_response()
    body["choices"][0]["message"]["tool_calls"] *= 2

    async def scenario():
        adapter, http_client = make_adapter(lambda request: httpx.Response(200, json=body))
        try:
            with pytest.raises(LLMError) as captured:
                await adapter.complete([], schemas)
            assert captured.value.code == "LLM_INVALID_RESPONSE"
        finally:
            await http_client.aclose()

    run(scenario())


def test_rejects_incomplete_or_inconsistent_finish_reasons(tmp_path):
    schemas = create_registry(Workspace(tmp_path)).schemas()
    cases = [
        (
            {
                **text_response(),
                "choices": [{**text_response()["choices"][0], "finish_reason": "length"}],
            },
            "LLM_RESPONSE_TRUNCATED",
        ),
        (
            {
                **text_response(),
                "choices": [{**text_response()["choices"][0], "finish_reason": "content_filter"}],
            },
            "LLM_RESPONSE_BLOCKED",
        ),
        (
            {
                **text_response(),
                "choices": [{**text_response()["choices"][0], "finish_reason": "tool_calls"}],
            },
            "LLM_INVALID_RESPONSE",
        ),
        (
            {
                **tool_response(),
                "choices": [{**tool_response()["choices"][0], "finish_reason": "stop"}],
            },
            "LLM_INVALID_RESPONSE",
        ),
    ]

    async def scenario():
        for body, expected_code in cases:
            adapter, http_client = make_adapter(
                lambda request, body=body: httpx.Response(200, json=body)
            )
            try:
                with pytest.raises(LLMError) as captured:
                    await adapter.complete([], schemas)
                assert captured.value.code == expected_code
            finally:
                await http_client.aclose()

    run(scenario())


def test_retries_transient_failures_and_honors_bounded_retry_after():
    calls = 0
    delays = []

    async def scenario():
        nonlocal calls

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ReadTimeout("private transport detail", request=request)
            if calls == 2:
                return httpx.Response(503, headers={"Retry-After": "99"})
            return httpx.Response(200, json=text_response())

        async def sleep(delay: float) -> None:
            delays.append(delay)

        adapter, http_client = make_adapter(
            handler,
            max_retries=2,
            retry_base_seconds=0.25,
            max_retry_delay_seconds=2,
            sleep=sleep,
        )
        try:
            assert (await adapter.complete([], [])).content == "done"
            assert calls == 3
            assert delays == [0.25, 2]
        finally:
            await http_client.aclose()

    run(scenario())


def test_timeout_exhaustion_is_safe_and_observable():
    calls = 0

    async def scenario():
        nonlocal calls

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("fixture-secret-key in private detail", request=request)

        adapter, http_client = make_adapter(handler, max_retries=2)
        try:
            with pytest.raises(LLMError) as captured:
                await adapter.complete([], [])
            error = captured.value
            assert error.code == "LLM_TIMEOUT"
            assert error.retryable and error.attempts == 3 and calls == 3
            assert "fixture-secret-key" not in str(error)
        finally:
            await http_client.aclose()

    run(scenario())


def test_non_retryable_http_error_does_not_expose_body_or_retry():
    calls = 0

    async def scenario():
        nonlocal calls

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(401, json={"error": "fixture-secret-key private body"})

        adapter, http_client = make_adapter(handler, max_retries=2)
        try:
            with pytest.raises(LLMError) as captured:
                await adapter.complete([], [])
            assert captured.value.code == "LLM_AUTH_ERROR"
            assert captured.value.status_code == 401
            assert not captured.value.retryable and calls == 1
            assert "fixture-secret-key" not in str(captured.value)
        finally:
            await http_client.aclose()

    run(scenario())


def test_close_is_idempotent_and_respects_client_ownership():
    async def scenario():
        adapter, http_client = make_adapter(
            lambda request: httpx.Response(200, json=text_response()),
            owns_client=True,
        )
        await adapter.close()
        await adapter.close()
        assert http_client.is_closed
        with pytest.raises(LLMError) as captured:
            await adapter.complete([], [])
        assert captured.value.code == "LLM_CLOSED"

    run(scenario())


def test_cancellation_is_not_retried():
    calls = 0

    async def scenario():
        nonlocal calls

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise asyncio.CancelledError

        adapter, http_client = make_adapter(handler, max_retries=2)
        try:
            with pytest.raises(asyncio.CancelledError):
                await adapter.complete([], [])
            assert calls == 1
        finally:
            await http_client.aclose()

    run(scenario())


@pytest.mark.parametrize(
    "tools",
    [
        [{"type": "function", "function": {"name": "missing-parameters"}}],
        [
            {
                "type": "function",
                "function": {"name": "same", "parameters": {}},
            },
            {
                "type": "function",
                "function": {"name": "same", "parameters": {}},
            },
        ],
    ],
)
def test_rejects_invalid_tool_schema_before_request(tools):
    calls = 0

    async def scenario():
        nonlocal calls

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=text_response())

        adapter, http_client = make_adapter(handler)
        try:
            with pytest.raises(LLMError) as captured:
                await adapter.complete([], tools)
            assert captured.value.code == "LLM_INVALID_TOOLS"
            assert calls == 0
        finally:
            await http_client.aclose()

    run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": ""},
        {"base_url": "file:///tmp/model"},
        {"base_url": "https://name:secret@model.example/v1"},
        {"model": ""},
        {"timeout_seconds": 0},
        {"max_retries": -1},
    ],
)
def test_configuration_validation(kwargs):
    values = {
        "api_key": "safe-key",
        "base_url": "https://model.example/v1",
        "model": "safe-model",
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        OpenAICompatibleLLMClient(**values)
