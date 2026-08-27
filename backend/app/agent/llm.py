from typing import Any, Protocol

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ModelReply(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMClient(Protocol):
    """Provider adapters must only translate HTTP/model messages, not run tools."""

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply: ...

    async def close(self) -> None: ...
