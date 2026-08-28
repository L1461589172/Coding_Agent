import asyncio
import json
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from math import isfinite
from time import time
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    name: str
    arguments: dict[str, Any]


class ModelReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMError(Exception):
    """A safe, observable model error that never includes provider response bodies."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = attempts


class LLMClient(Protocol):
    """Provider adapters must only translate HTTP/model messages, not run tools."""

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply: ...

    async def close(self) -> None: ...


class _FunctionCall(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    name: str
    arguments: str

    @field_validator("name")
    @classmethod
    def non_empty_name(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("Invalid function name")
        return value


class _ResponseToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: str
    type: Literal["function"]
    function: _FunctionCall

    @field_validator("id")
    @classmethod
    def non_empty_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("Invalid tool call id")
        return value


class _AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    role: Literal["assistant"]
    content: str | None = None
    tool_calls: list[_ResponseToolCall] | None = None


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    index: int
    message: _AssistantMessage
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"]


class _ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    choices: list[_Choice] = Field(min_length=1, max_length=1)


Sleep = Callable[[float], Awaitable[None]]


class OpenAICompatibleLLMClient:
    """Minimal OpenAI-compatible Chat Completions HTTP adapter."""

    RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        owns_client: bool | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> "OpenAICompatibleLLMClient":
        return cls(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            timeout_seconds=settings.llm_timeout_seconds,
            connect_timeout_seconds=settings.llm_connect_timeout_seconds,
            max_retries=settings.llm_max_retries,
            client=client,
            owns_client=owns_client,
            sleep=sleep,
        )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        connect_timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_base_seconds: float = 0.25,
        max_retry_delay_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
        owns_client: bool | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("api_key is required")
        if not model or not model.strip():
            raise ValueError("model is required")
        if (
            not isfinite(timeout_seconds)
            or not isfinite(connect_timeout_seconds)
            or timeout_seconds <= 0
            or connect_timeout_seconds <= 0
        ):
            raise ValueError("LLM timeouts must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if (
            not isfinite(retry_base_seconds)
            or not isfinite(max_retry_delay_seconds)
            or retry_base_seconds < 0
            or max_retry_delay_seconds < 0
        ):
            raise ValueError("LLM retry delays must be non-negative")
        if owns_client is True and client is None:
            raise ValueError("owns_client=True requires an injected client")

        self._endpoint = self._build_endpoint(base_url)
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None if owns_client is None else owns_client
        self._sleep = sleep
        self._closed = False
        self._close_lock = asyncio.Lock()

    @staticmethod
    def _build_endpoint(base_url: str) -> str:
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required")
        normalized = base_url.rstrip("/")
        endpoint = (
            normalized
            if normalized.endswith("/chat/completions")
            else f"{normalized}/chat/completions"
        )
        try:
            parsed = httpx.URL(endpoint)
        except (TypeError, ValueError) as exc:
            raise ValueError("base_url must be a valid HTTP(S) URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.host
            or bool(parsed.username)
            or bool(parsed.password)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be a valid HTTP(S) URL without credentials or query")
        return str(parsed)

    async def __aenter__(self) -> "OpenAICompatibleLLMClient":
        if self._closed:
            raise LLMError("LLM_CLOSED", "Model client is closed")
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_client:
                await self._client.aclose()

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        if self._closed:
            raise LLMError("LLM_CLOSED", "Model client is closed")

        tool_names = self._validate_tool_schemas(tools)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            # Keep the ToolRegistry-produced schemas intact; this adapter does not recreate them.
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        attempts = self._max_retries + 1
        for attempt in range(attempts):
            if self._closed:
                raise LLMError("LLM_CLOSED", "Model client is closed", attempts=attempt + 1)
            try:
                response = await self._client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout,
                )
            except httpx.TimeoutException:
                if attempt < self._max_retries:
                    await self._sleep(self._retry_delay(attempt, None))
                    continue
                raise LLMError(
                    "LLM_TIMEOUT",
                    "Model request timed out",
                    retryable=True,
                    attempts=attempt + 1,
                ) from None
            except httpx.TransportError:
                if attempt < self._max_retries:
                    await self._sleep(self._retry_delay(attempt, None))
                    continue
                raise LLMError(
                    "LLM_NETWORK_ERROR",
                    "Model service is unavailable",
                    retryable=True,
                    attempts=attempt + 1,
                ) from None

            if response.status_code in self.RETRYABLE_STATUS_CODES:
                if attempt < self._max_retries:
                    await self._sleep(
                        self._retry_delay(attempt, response.headers.get("Retry-After"))
                    )
                    continue
                raise self._http_error(response.status_code, attempt + 1, retryable=True)
            if response.is_error:
                raise self._http_error(response.status_code, attempt + 1, retryable=False)
            return self._parse_response(response, tool_names)

        raise AssertionError("Retry loop exhausted without returning or raising")

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        delay = min(self._retry_base_seconds * (2**attempt), self._max_retry_delay_seconds)
        if not retry_after:
            return delay
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                seconds = retry_at.timestamp() - time()
            except (TypeError, ValueError, OverflowError):
                return delay
        if not isfinite(seconds) or seconds < 0:
            return delay
        return min(seconds, self._max_retry_delay_seconds)

    @staticmethod
    def _http_error(status_code: int, attempts: int, *, retryable: bool) -> LLMError:
        if status_code in {401, 403}:
            code = "LLM_AUTH_ERROR"
            message = "Model service rejected authentication"
        elif status_code == 429:
            code = "LLM_RATE_LIMIT"
            message = "Model service rate limit exceeded"
        elif status_code >= 500:
            code = "LLM_SERVICE_ERROR"
            message = "Model service failed"
        else:
            code = "LLM_HTTP_ERROR"
            message = f"Model service returned HTTP {status_code}"
        return LLMError(
            code,
            message,
            retryable=retryable,
            status_code=status_code,
            attempts=attempts,
        )

    @staticmethod
    def _validate_tool_schemas(tools: list[dict[str, Any]]) -> frozenset[str]:
        names: set[str] = set()
        for schema in tools:
            function = schema.get("function") if isinstance(schema, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            parameters = function.get("parameters") if isinstance(function, dict) else None
            if (
                not isinstance(schema, dict)
                or schema.get("type") != "function"
                or not isinstance(name, str)
                or not name
                or name != name.strip()
                or not isinstance(parameters, dict)
            ):
                raise LLMError("LLM_INVALID_TOOLS", "Tool schemas are invalid")
            if name in names:
                raise LLMError("LLM_INVALID_TOOLS", "Tool schema names must be unique")
            names.add(name)
        return frozenset(names)

    @staticmethod
    def _parse_response(response: httpx.Response, tool_names: frozenset[str]) -> ModelReply:
        try:
            raw = response.json()
            parsed = _ChatCompletionResponse.model_validate(raw)
        except (ValueError, ValidationError):
            raise LLMError(
                "LLM_INVALID_RESPONSE", "Model service returned an invalid response"
            ) from None

        choice = parsed.choices[0]
        message = choice.message
        calls: list[ToolCall] = []
        seen_ids: set[str] = set()
        for call in message.tool_calls or []:
            if call.id in seen_ids:
                raise LLMError("LLM_INVALID_RESPONSE", "Model returned duplicate tool call ids")
            seen_ids.add(call.id)
            if call.function.name not in tool_names:
                raise LLMError("LLM_UNKNOWN_TOOL", "Model requested an unknown tool")
            try:
                arguments = json.loads(call.function.arguments)
            except (json.JSONDecodeError, TypeError):
                raise LLMError(
                    "LLM_INVALID_RESPONSE", "Model returned invalid tool arguments"
                ) from None
            if not isinstance(arguments, dict):
                raise LLMError("LLM_INVALID_RESPONSE", "Model tool arguments must be a JSON object")
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))

        content = message.content or ""
        if choice.finish_reason == "length":
            raise LLMError("LLM_RESPONSE_TRUNCATED", "Model response reached its output limit")
        if choice.finish_reason == "content_filter":
            raise LLMError("LLM_RESPONSE_BLOCKED", "Model response was blocked")
        if choice.finish_reason == "tool_calls" and not calls:
            raise LLMError("LLM_INVALID_RESPONSE", "Model omitted declared tool calls")
        if choice.finish_reason == "stop" and calls:
            raise LLMError("LLM_INVALID_RESPONSE", "Model returned inconsistent tool calls")
        if not content.strip() and not calls:
            raise LLMError("LLM_INVALID_RESPONSE", "Model returned an empty response")
        return ModelReply(content=content, tool_calls=calls)
