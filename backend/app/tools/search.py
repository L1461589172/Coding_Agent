from pydantic import BaseModel, Field

from app.tools.base import ToolArgs, ToolResult, ToolSpec


class SearchTextArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=1000)
    path: str = "."
    max_results: int = Field(default=50, ge=1, le=200)


async def search_text(arguments: BaseModel) -> ToolResult:
    return ToolResult(
        ok=False, error_code="NOT_IMPLEMENTED", error_message="文本搜索将在 M1 实现。"
    )


def search_spec() -> ToolSpec:
    return ToolSpec("search_text", "Search text inside the workspace", SearchTextArgs, search_text)
